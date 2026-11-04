# Last update 5/25/2026 11:26:48 AM

from machine import Pin, ADC, SoftI2C, RTC, reset, PWM
import time, math, struct, array, os, socket, network, json, gc, errno

startupTime = time.ticks_ms()

# Initialization - LED blinks on Pico to announce start of program
picoLed = Pin("LED", Pin.OUT)
for i in range(5):
    picoLed.value(1)
    time.sleep(0.12)
    picoLed.value(0)
    time.sleep(0.12)

# Tank low sensor
lowSensor = Pin(0, Pin.IN, Pin.PULL_DOWN)

# Tank high sensor
highSensor = Pin(1, Pin.IN, Pin.PULL_DOWN)

# Turn well pump On/Off
wellPumpOnOff = Pin(4, Pin.OUT)
wellPumpOnOff.value(0)

# Monitor if well pump is getting power. 0 = on, 1 = off
wellPumpPower = Pin(12, Pin.IN, Pin.PULL_UP) 

# Function to reverse wellPumpPower
def isPumpOn():
    return not getStableValue(wellPumpPower)

# Monitor if house pump is getting power. 0 = on, 1 = off
housePumpPower = Pin(11, Pin.IN, Pin.PULL_UP)

# Function to reverse housePumpPower
def isHousePumpOn():
    return not getStableValue(housePumpPower)

# Pin for turning secondary well pump on
secondaryPumpOnOff = Pin(13, Pin.OUT)
secondaryPumpOnOff.value(0)

# Pin for getting signal from other Pico telling if there is flow in the water line
waterFlow = Pin(17, Pin.IN)

# Pressure sensor in tank for level
levelSensor = ADC(Pin(28))

# Buttons -- Unfortunatly, Pin 6 burnt out...
button1 = Pin(5, Pin.IN, Pin.PULL_DOWN)
button2 = Pin(7, Pin.IN, Pin.PULL_DOWN)
button3 = Pin(8, Pin.IN, Pin.PULL_DOWN)
button4 = Pin(9, Pin.IN, Pin.PULL_DOWN)
button1Pressed = button2Pressed = button3Pressed = button4Pressed = False
button1Timer = button2Timer = time.ticks_ms()

# Speed control for booster pump
boosterPumpSpeed = PWM(Pin(2))
boosterPumpSpeed.freq(500)

# Function to set speed of booster pump
def setPumpSpeed(spdPct):
    if spdPct > 100: spdPct = 100
    elif spdPct < 0: spdPct = 0
    if 0 < spdPct < 100:
        boosterPumpSpeed.duty_u16(65535)
        time.sleep_ms(250)
    boosterPumpSpeed.duty_u16(int((spdPct / 100) * 65535))

# Instead of using Pin.value(), which might have noise, use this to get the average result
def getStableValue(pin):
    return 1 if sum(pin.value() for _ in range(10)) > 5 else 0

# I2C Setup - For communication with display board
i2c = SoftI2C(scl=Pin(15), sda=Pin(14), freq=100_000)
lcdAddr = 39

# LCD Command Helper -- IDK how this works, AI wrote it
def lcdWrite(cmd, rs=0, light=0x00):
    base = (rs << 0) | light
    dataHigh = (cmd & 0xF0)
    dataLow = ((cmd << 4) & 0xF0)

    def pulseEn(data):
        enLow  = base | data
        enHigh = base | data | 0x04 # 0x04 is Enable pin
        i2c.writeto(lcdAddr, bytes([enLow, enHigh, enLow]))

    pulseEn(dataHigh)
    pulseEn(dataLow)
    time.sleep(0.001)  # Short delay for command processing


# Initialization of display screen
def lcdInit():
    time.sleep(0.1)
    lcdWrite(0x33)  
    time.sleep(0.005)      
    lcdWrite(0x33)  
    time.sleep(0.005)
    lcdWrite(0x32)  # Switch to 4-bit mode
    time.sleep(0.005)
    
    lcdWrite(0x28)  # 2 lines, 5x8 font
    lcdWrite(0x0C)  # Display ON, backlight ON
    lcdWrite(0x06)  # Increment cursor (Standard)
    lcdWrite(0x01)  # Clear screen
    time.sleep(0.2)       

# Command to display text on screen
def lcdPrint(text, line=0, col=0,light=0x08):
    lineOffsets = [0x00, 0x40, 0x14, 0x54]
    lcdWrite(0x80 | (lineOffsets[line] + col))
    for char in text:
        lcdWrite(ord(char), rs=1,light=light)
    
# Turn on Display
lcdInit()
lcdPrint("Powering on...", 0, 3, light=0x08)
clearLCD = time.ticks_ms()
screenTimeout = 8000
screenOn = True

tankFull = False

# Logic to see if tank is full or needs pumping
def checkSensors(full):
    if not getStableValue(lowSensor) and not getStableValue(highSensor): # Both Sensors OFF
        pump = True
        full = False
    elif getStableValue(lowSensor) and getStableValue(highSensor): # Both Sensors ON
        pump = False
        full = True
    else: # Low Sensor ON and High Sensor OFF, or any other abnormal situations
        if not full:
            pump = True
        else:
            pump = False
    return pump, full

smoothedGalVoltage = None

# Function to stop spikes from bad readings, and comparing it to the last updated of GallonsInTank
def getStableVoltage():
    global smoothedGalVoltage
    
    samples = sorted([levelSensor.read_u16() for _ in range(1001)])
    rawVol = samples[500]
    
    if smoothedGalVoltage is None:
        smoothedGalVoltage = rawVol
        
    alpha = 0.1
    smoothedGalVoltage = (alpha * rawVol) + (1 - alpha) * smoothedGalVoltage
    
    return smoothedGalVoltage

# Init for smoothedGalVoltage
for i in range(40):
    getStableVoltage()

# Function to calculate the gallons currently in tank 
def gallonsInTank():
    smoothedGalVoltage = getStableVoltage()
    feetWater = smoothedGalVoltage/6553.5
    # This number, currently "6553.5" can be adjusted, depending on the accuracy of the sensor
    # It is 6553.5 = 65535 * 0.33 / 3.3
    # 3.3V can be adjusted depending on the voltage of the pico (ie. 3.295V, 3.305V)
    # 65535 cannot be adjsuted, since it is 3.3V mapped across a 16 bit integer (0-65535 levels) 
    # 0.33 can be adjusted (ie. 3295) as this is the feet per volt so 0.33V/foot of water

    if feetWater <= 6.3: # After 6.3 feet, the cylinder ends and the dome part of the tank begins
        volume = feetWater*math.pi*3.98351**2 # 3.98351 length in feet of tank radius 
    else:
        volumeCyl = 6.3*math.pi*3.98351**2
        volumeDome = domeLookupGal(feetWater)
        volume = volumeCyl + volumeDome
    gallons = volume*7.48052 # Cu ft -> gal
    return gallons

# Function to lookup dome gallons
def domeLookupGal(feetWater):
    offset = feetWater - 6.3
    index = int(offset / 0.01)
    fraction = (offset / 0.01) - index
    
    index = int((offset) / .01)
    if index >= len(domeLookup):
        return domeLookup[-1]
    
    elif index == 0:
        y0 = 0
        y1 = domeLookup[0]
        return y0 + (y1 - y0) * fraction
    
    else:
        y0 = domeLookup[index - 1]
        y1 = domeLookup[index]
        return y0 + (y1 - y0) * fraction

# Look at DomeCalculation.py for math
domeLookup = array.array('f', [0.48849308490753174, 0.9728114008903503, 1.4530082941055298, 1.9291026592254639, 2.401124954223633, 2.8690719604492188, 3.332979679107666, 3.792837619781494, 4.248657703399658, 4.700455188751221, 5.14822244644165, 5.591967582702637, 6.0317158699035645, 6.4674553871154785, 6.899177074432373, 7.326902389526367, 7.750642776489258, 8.170391082763672, 8.586134910583496, 8.997889518737793, 9.405674934387207, 9.80948543548584, 10.20930004119873, 10.605113983154297, 10.99697494506836, 11.384862899780273, 11.768781661987305, 12.14870548248291, 12.524632453918457, 12.896612167358398, 13.264630317687988, 13.628674507141113, 13.988716125488281, 14.344761848449707, 14.696866035461426, 15.045019149780273, 15.389184951782227, 15.729350090026855, 16.065500259399414, 16.397714614868164, 16.725976943969727, 17.050254821777344, 17.370513916015625, 17.686735153198242, 17.9990177154541, 18.30735206604004, 18.6117000579834, 18.912012100219727, 19.20823860168457, 19.500520706176758, 19.788867950439453, 20.07331657409668, 20.35352325439453, 20.629493713378906, 20.901994705200195, 21.17030906677246, 21.434406280517578, 21.69441032409668, 21.950613021850586, 22.202756881713867, 22.450727462768555, 22.694595336914062, 22.934463500976562, 23.17034339904785, 23.40204429626465, 23.629621505737305, 23.85312271118164, 24.07257652282715, 24.28784942626953, 24.498960494995117])

"""
Binary Storage Format Documentation:
----------------------------------------------------
[ Data Type ] [ Description ]
   uint16       Minimum gallons
   uint16       Maximum gallons
   uint8        Year
   uint8        Month
   uint8        Day
   uint8        Time when the low was recorded
   uint8        Time when the high was recorded
   uint16       How much was filled during the 24 period
   uint8        How confident the fill data is
   uint16       Level of tank at 3 AM (reset time)
   unit16       How long the tank was being filled (1 = 6 seconds)
uint16 range (0-65,535), uint8 range (0-255)
"""

# Function to save tank data to file
def saveTankData(minGal, maxGal, timeMin, timeMax, filled, filledConfidence, currentLevel, timeFill):
    """Save daily data to binary file with prior day's date"""
    yesterday = getTime(['y','mon','d','wd'],goBack=86400)
    confidenceBinary = round(filledConfidence*255) # uses 0-255 scaling instead of 0-100 percentage scaling
    with open('tank_data.bin', 'ab+') as f:
        f.write(struct.pack('<HHBBBBBHBHH',
                            minGal, 
                            maxGal,
                            yesterday[0] - 2000, # Year counts from 2000, saving space
                            yesterday[1],
                            yesterday[2],
                            int(timeMin*10),
                            int(timeMax*10),
                            round(filled),
                            confidenceBinary, 
                            currentLevel,
                            int(timeFill / 6) # Why (timeFill / 6)? because it was saved like this before improvements, and thus the .bin file is saved as every 6 seconds, not every second
                            ))
    latestRecord = [yesterday[1], yesterday[2], yesterday[0], yesterday[3], minGal, maxGal, timeMin, timeMax, round(filled), confidenceBinary / 255, currentLevel, timeFill]
    return latestRecord

# Function to load 100 days of previous tank data
def loadTankData():
    records = []
    fileSize = os.stat('tank_data.bin')[6]
    totalRecords = fileSize // 16
    startRecord = max(0, totalRecords - 100)
    
    with open('tank_data.bin', 'rb') as f:
        f.seek(startRecord * 16)  
        while True:
            data = f.read(16)
            if not data or len(data) != 16:
                break
            records.append(struct.unpack('<HHBBBBBHBHH', data))
                
    formatted = []
    for minGal, maxGal, yr, mon, day, tMin, tMax, filled, conf, curr, fillT in records:
        timestamp = time.mktime((yr + 2000, mon, day, 0, 0, 0, 0, 0, -1))
        wday = time.localtime(timestamp)[6]  # 0=Monday, 6=Sunday
        formatted.append([mon, day, yr + 2000, wday, minGal, maxGal, tMin/10, tMax/10, filled, conf / 255, curr, fillT])
        
    return formatted

tankRecords = loadTankData()

# Function to display the historic highs and lows of the tank data
def displayRecords(providedRecords, high, low, selectedRange):
    lcdWrite(0x01, light=0x08)
    if len(providedRecords) - 3 < selectedRange:
        selectedRange = len(providedRecords) - 3

    if selectedRange == 0:
        selectedRecords = providedRecords[-1:-4:-1]
        startLine = 1
        day, month, weekDay = getTime(['d','mon','wd'])
        lcdPrint(f"{month:02}/{day:02} {Days[weekDay]} {low:04} {high:04}",0,light=0x08)
        
    else:
        selectedRecords = providedRecords[-selectedRange:-4-selectedRange:-1]
        startLine = 0
    
    for i, val in enumerate(selectedRecords):
        lcdPrint(f"{val[0]:02}/{val[1]:02} {Days[val[3]]} {val[4]:04} {val[5]:04}",i+startLine,light=0x08)

    time.sleep(0.5)
    
    return selectedRange

# Function to display the how much filled each day and what the net change was
def displayFillChange(providedRecords, selectedRange):
    lcdWrite(0x01, light=0x08)
    if len(providedRecords) - 3 < selectedRange:
        selectedRange = len(providedRecords) - 3
    selectedRecords = providedRecords[-1-selectedRange:-5-selectedRange:-1]
    for i, val in enumerate(selectedRecords):
        lcdPrint(f"{val[0]:02}/{val[1]:02} {Days[val[3]]} {val[8]:04} {val[10]:04}",i,light=0x08)
    return selectedRange

# Initialize RTC (Real Time Clock)
rtc = RTC()

Days = ('Mon','Tue','Wed','Thu','Fri','Sat','Sun')

# Function to better format getting time
def getTime(part, goBack=0, date=None): # goBack in seconds
    if date is not None:
        sec = time.mktime((date[0], date[1], date[2], 0, 0, 0, -1, -1, -1))
        Ctime = time.localtime(sec - (goBack))
    else:
        Ctime = time.localtime(time.time() - goBack)
    times = []
    for i in part:
        if i == 'y':     # Year
            times.append(Ctime[0])
        elif i == 'mon': # Month
            times.append(Ctime[1])
        elif i == 'd':   # Day
            times.append(Ctime[2])
        elif i == 'h':   # Hour
            times.append(Ctime[3])
        elif i == 'min': # Minute
            times.append(Ctime[4])
        elif i == 's':   # Second
            times.append(Ctime[5])
        elif i == 'wd':  # Weekday (0=Monday)
            times.append(Ctime[6])
    return times

# Function to find closest date in records for Trend viewing
def findClosestRecord(date):
    # year, month, day
    targetSec = time.mktime((date[0], date[1], date[2], 0, 0, 0, -1, -1, -1))

    bestRecord = None
    bestDiff = float('inf')
    daysOff = 0

    for record in reversed(tankRecords):
        rMon = record[0]
        rDay = record[1]
        rYr = record[2]

        recordSec = time.mktime((rYr, rMon, rDay, 0, 0, 0, -1, -1, -1))
        diff = recordSec - targetSec
        currentDiff = abs(diff)

        if currentDiff < bestDiff:
            bestDiff = currentDiff
            bestRecord = record	
            daysOff = diff / 86400
            
            if diff == 0:
                daysOff = 0
                break
        
        elif currentDiff > bestDiff:
            break
        
        else:
            daysOff = diff / 86400
            bestRecord = record
            break
    
    bestIndex = tankRecords.index(bestRecord)
    return bestIndex, daysOff

# Backup of various variables in case of power loss
def saveHighLow(num1, num2, time1, time2, fillData, num3):
    with open("temp_high_low.txt", "w") as f:
        f.write(f"{getTime(['y','mon','d'])}\n{num1} {num2} {num3} {time1} {time2}")
        for i in fillData:
            f.write(f"\n{i[0]} {i[1]}")

# Load backup variables
def loadHighLow():
    with open("temp_high_low.txt", "r") as f:
        line = f.readlines()
        currentDay = str(getTime(['y','mon','d']))
        fillData = []
        if currentDay == line[0].strip():
            num1, num2, num3, time1, time2 = line[1].split()
            if len(line) > 2:
                line = line[2:]
                for i in line:
                    split = i.split()
                    fillData.append([float(split[0]),float(split[1])])
            return num1, num2, num3, time1, time2, fillData
        else:
            return None

# Temporary while correct time from internet is loading
high = low = tempH = tempL = round(gallonsInTank())
tankTimeFill = 0
hour, minute = getTime(['h','min'])   
timestampMin = timestampMax = hour + round(minute/6)/10
tankFill24Hours = []

# Takes an average of the flow signal from the second pico, loosely catching any electrical noise
def waterFlowCheck(flowList, previousFlow):
    flowList.append(getStableValue(waterFlow))
    if len(flowList) > 50:
        del flowList[0]
    flowListCount = sum(flowList)
    if flowListCount >= 48:
        return flowList, True
    elif flowListCount <= 2:
        return flowList, False
    else:
        return flowList, previousFlow

# Main screen display
def displayStatus(showRestart=False, timeR=0):
    lcdWrite(0x01, light=0x08)
    gal = gallonsInTank()
    lcdPrint("Tank Status:",0,4,light=0x08)
    lcdPrint(f"{round(gal)} g",1,7,light=0x08)
    lcdPrint(f"{percentTank(gal)} %",2,7,light=0x08) 
    if showRestart:
        if wellPumpOnOff.value() == 1:
            lcdPrint("Well pumping",3,4,light=0x08)
        elif timeR <= 0:
            lcdPrint("Tank Full",3,5,light=0x08)
        else:
            lcdPrint(f"Well Restarts {timeR} m",3,0,light=0x08)
    return True, "status"

# Displays change of 3 am readings in the specified trend period
def displayOverallChange(trendPeriod):
    lcdWrite(0x01, light=0x08)
    lcdPrint("Overall Change",0,3,light=0x08)

    for i,val in enumerate(trendPeriod):
        if val > 6 and val % 7 == 0:
            days = "{:<4}".format(str(round(val/7)) + "w")
        else:
            days = "{:<4}".format(str(val) + "d")
        try:
            date1 = (tankRecords[-1][2], tankRecords[-1][0], tankRecords[-1][1])
            date2 = getTime(['y','mon','d'],  86400 * (val - 1), date1)
            matchingIndex, daysOff = findClosestRecord(date2)
            
            change = tankRecords[-1][10]-tankRecords[matchingIndex][10]
            averageChange = (change/(val-1-daysOff))
            
            if change >= 0: plus = "+"
            else: plus = ""
            
            averageFormatted = (f"{averageChange:.1f}" if abs(averageChange) < 100 else f"{averageChange:<4.0f}").strip()
            spacesBetween = 11 - len(str(change)) - len(str(averageFormatted)) - 2*len(plus)
            lcdPrint(f"{days}{plus}{change}{' ' * spacesBetween}{plus}{averageFormatted}/day",i+1,light=0x08)
        
        except:
            lcdPrint(f"No data for {days}",i+1,0,light=0x08)

# Displays how much water is poured into the tank in the specified trend period
def displayDailyFill(trendPeriod):
    trendPeriod.sort()
    lcdWrite(0x01, light=0x08)
    lcdPrint("Daily Fill",0,5,light=0x08)
    for i,val in enumerate(trendPeriod):
        if val > 6 and val % 7 == 0:
            days = "{:<4}".format(str(round(val/7)) + "w")
        else:
            days = "{:<4}".format(str(val) + "d")
        
        totalDraw = 0
        try:
            date1 = (tankRecords[-1][2], tankRecords[-1][0], tankRecords[-1][1])
            date2 = getTime(['y','mon','d'],  86400 * (val - 1), date1)
            matchingIndex, daysOff = findClosestRecord(date2)

            for j in range(matchingIndex, len(tankRecords)):
                totalDraw += tankRecords[j][8]
            avgDraw = totalDraw/(val - daysOff)
            if avgDraw >= 0: plus = "+"
            else: plus = ""
            
            avgDraw = (f"{avgDraw:.1f}" if abs(avgDraw) < 100 else f"{avgDraw:<4.0f}").strip()
            spacesBetween = 10 - len(str(totalDraw)) - len(avgDraw)
            lcdPrint(f"{days}{plus}{totalDraw}{' ' * spacesBetween}{plus}{avgDraw}/day",i+1,0,light=0x08)
        except:
            lcdPrint(f"No data for {days}",i+1,0,light=0x08)

# Display the menu to select settings to edit
def displaySettings(providedRecords,selected):
    lcdWrite(0x01, light=0x08)
    selectedRange = selected
    if len(providedRecords) <= selected: selected = len(providedRecords) - 1
    if len(providedRecords) - 4 < selectedRange:
        selectedRange = len(providedRecords) - 3

    if selectedRange == 0:
        selectedRecords = providedRecords[:3]
        startLine = 1
        lcdPrint("Settings",0,6,light=0x08)
        
    else:
        selectedRecords = providedRecords[selectedRange-1:3+selectedRange]
        startLine = 0
    
    for i, val in enumerate(selectedRecords):
        if val == settings[selected]: selectedItem = "-"
        else: selectedItem = ""
        lcdPrint(f"{selectedItem}{selectedRecords[i]}",i+startLine,light=0x08)
    
    return selected

# Shows descripitons and settings to edit
def displaySettingsEdit(selectedItem, numOnly=False):
    lcdWrite(0x01, light=0x08)
    if not numOnly:
        for i, val in enumerate(settingsDesc[selectedItem]):
            lcdPrint(f"{val}",i,0,light=0x08)
    lcdPrint(f"{settingsOptions[selectedItem]}",3,0,light=0x08)

try:
    with open('temp_tankReadings.bin', 'rb') as f:
        data = f.read(4)
        tRPointer = struct.unpack('<I', data)[0]
        
        tankReadingsRecord = array.array('f')
        tankReadingsRecord.fromfile(f, 10080)
        
        loadedTankReadings = True
        
    os.remove('temp_tankReadings.bin')
    
except:
    level = round(gallonsInTank(),1)
    tankReadingsRecord = array.array('f', [level] * 10080)
    tRPointer = 0 # Needs to be set to correct time, automatically done with syncRtc
    loadedTankReadings = False

tRCounter = tRSum = 0
tankReadingsTimer = time.ticks_ms()
pumpInStart = pumpInStop = 0
pumpOutStart = pumpOutStop = 0
pumpOutWhilePumpIn = False
secondaryPumpWasOff = True
recordedPumpOutStart = False

# Function to get seconds past midnight
def secondsFM(): # secondsFromMidnight
    h, m, s = getTime(['h', 'min', 's'])
    return h * 3600 + m * 60 + s

# Calculate the part where only the well pump was on
# Calculated flow of the full duration, based on the average flow * flow time
def calculatePartialFlow(start, stop, totalRuntime, startGal, stopGal, secondaryStart=None, secondaryStop=None, secondaryStartGal=None, secondaryStopGal=None):
    if (stop - start) % 86400 <= 1: 
        return 0, 0

    if secondaryStart == None:
        count = (stop - start) % 86400
        
        if count < 30:
            return 0, 0
        
        meanDiff = (stopGal - startGal) / count
        ratioOn = count / totalRuntime
        calcFill = meanDiff * totalRuntime
        return calcFill, ratioOn
    
    else:
        count = (stop - start) % 86400
        meanDiff = (stopGal - startGal) / count
        
        count2 = (secondaryStop - secondaryStart) % 86400
        meanDiff2 = (secondaryStopGal - secondaryStartGal) / count2 
        
        if count2 < 30:
            ratioOn = count / totalRuntime
            calcFill = meanDiff * totalRuntime
            return calcFill, ratioOn
        elif count < 30:
            ratioOn = count2 / totalRuntime
            calcFill = meanDiff2 * totalRuntime
            return calcFill, ratioOn
        
        ratioOn = (count + count2) / totalRuntime
        meanMeanDiff = (meanDiff * count + meanDiff2 * count2) / (count + count2)
        calcFill = meanMeanDiff * totalRuntime
        
        return calcFill, ratioOn

# Save settings
def saveSettings():
    global settingsOptions, wellPumpSetting, secondaryPumpSetting, dryWellResetTime
    
    wellPumpSetting = settingsOptions[0]
    secondaryPumpSetting = settingsOptions[1]
    dryWellResetTime = settingsOptions[2] * 60000
    setPumpSpeed(settingsOptions[5])
    
    with open("settings.txt", "w") as f:
        for i, val in enumerate(settingsOptions):
            if i <= 2 or i == 5: f.write(f"{val} ")
            else:
                for j in val: f.write(f"{j} ")

# When turns on loads up settings that were saved
def loadSettings():
    with open("settings.txt", "r") as f:
        line = f.read().split(" ")[:-1]
        line = [int(x) for x in line]
        loadedSettings = [line[0],line[1],line[2],[line[3],line[4],line[5]],[line[6],line[7],line[8]],line[9]]
        return loadedSettings

settingsOptions = loadSettings()
wellPumpSetting = settingsOptions[0]
secondaryPumpSetting = settingsOptions[1]
dryWellResetTime = settingsOptions[2]*60000
setPumpSpeed(settingsOptions[5])

def calculateConfidence(cleanRatio):
    if cleanRatio >= 1.0: return 1.0
    if cleanRatio <= 0.0: return 0.0
    
    if cleanRatio >= 0.60:
        conf = 0.75 + (0.25 * cleanRatio)
        
    elif cleanRatio >= 0.40:
        # Zone: Reliable Estimate
        # 40% clean -> 80% conf | 60% clean -> 90% conf
        # Linear slope: (0.90 - 0.80) / (0.60 - 0.40) = 0.77
        conf = 0.6 + (0.5 * cleanRatio)
        
    elif cleanRatio >= 0.20:
        conf = 0.4 + (1 * cleanRatio)
    
    else:
        conf = 3 * cleanRatio
        
    return max(0.0, min(1.0, conf))

def percentTank(g):
    # Edit these 2 values to denote the drain hole(empty) and fill hole(full) of the tank
    empty = 120
    full = 2450
    percent =  ((g - 120) / (full - empty)) * 100
    if percent <= 0: return "0.0"
    elif percent >= 100: return "100"
    else: return f"{percent:.1f}"

dayBefore = -1
checkLowHighTimer = time.ticks_ms()
buttonSelection = "off"
wellDry = False
wellTurnOnGraceTime = time.ticks_ms()
dryWellTime = time.ticks_ms()
wellDryTimeJustEnded = True
secondaryPumpSettingSpeed = False
turnOnSecondary = True
waterFlowCheckTimer = time.ticks_ms()
waterFlowList = []
waterCurrentlyFlowing = False
saveLater = False
saveLaterList = []
reSynctRPointer = False
daysToReset = 0

historyRange = 0
historyRangeFill = 0
settings = ["Well Pump","Booster Well Pump","Dry Interval","Trend Period (OC)","Trend Period (ADD)","Booster Pump Speed"]
settingsDesc = [["Well Pump","0-Off  1-On  2-Auto"],["Booster Well Pump","0-Off  1-On  2-Auto"],["Must be >= Dry Well ", "Relay interval"],["Pick time periods","to track for trend:","Overall Change"],["Pick time periods","to track for trend:","Average Daily Draw"],["Booster Pump","Percent Speed"]]
settingsTrendEdit = 0
selectedSettingIndex = 0

# Wifi
with open("wifi.txt", "r") as f:
    wifiTXT = f.readlines()
    ssid = wifiTXT[0].strip()
    password = wifiTXT[1].strip()

with open("index.html", "r") as f:
    htmlTemplate = f.read()

class wifiHandler:
    def __init__(self, conn):
        self.conn = conn
        self.rfile = conn.makefile('rb')
        self.wfile = conn.makefile('wb')
        self.headers = {}
        self.path = ""
        self.method = ""

    def handleOneRequest(self):
        try:
            # 1. Parse Request Line
            requestLine = self.rfile.readline().decode('utf-8').strip()
            if not requestLine:
                return False
            
            parts = requestLine.split()
            if len(parts) < 2:
                return False
            
            self.method = parts[0]
            self.path = parts[1]
            
            # 2. Parse Headers
            while True:
                line = self.rfile.readline().decode('utf-8').strip()
                if line == "":
                    break
                if ": " in line:
                    key, val = line.split(": ", 1)
                    self.headers[key] = val
            
            # 3. Route Request
            if self.method == 'GET':
                self.do_GET()
            elif self.method == 'POST':
                self.do_POST()
                
        except Exception as e:
            print("Handler Error:", e)
        
        return True
    
    def sendResponse(self, code, message="OK"):
        self.wfile.write(f"HTTP/1.1 {code} {message}\r\n".encode())

    def sendHeader(self, key, value):
        self.wfile.write(f"{key}: {value}\r\n".encode())

    def endHeaders(self):
        self.wfile.write("\r\n".encode())

    def sendError(self, code, message):
        self.sendResponse(code, message)
        self.sendHeader('Content-type', 'text/plain')
        self.endHeaders()
        self.wfile.write(message.encode())

    def do_GET(self):
        if self.path == '/download_data_csv':
            self.sendCsv()
            return
        elif self.path == '/download_metadata':
            self.sendMetadata()
            return
        elif '/get_table_data' in self.path:
            self.sendJsonData()
            return
        elif self.path == '/get_data_info':
            self.sendDataInfo()
            return
        else:            
            gal = round(gallonsInTank())
            percent = percentTank(gal)
            timeLeftReset = round((((dryWellResetTime + 180000) - time.ticks_diff(time.ticks_ms(), dryWellTime)) / 60000))
            pumpOnStr = str(isPumpOn())
            
            hours = (tRPointer // 60) % 24
            minutes = (tRPointer % 60) // 1
            
            timeStr = f"{hours:02d}:{minutes:02d}:00"
            
            self.sendResponse(200)
            self.sendHeader('Content-type', 'text/html')
            self.endHeaders()
            
            htmlBytes = htmlTemplate.encode('utf-8')
        
            # Saves memory using this instead of trying to create new strings
            def injectChunk(startPos, placeholder, replacementStr):
                # Find placeholder
                phBytes = placeholder.encode('utf-8')
                endPos = htmlBytes.find(phBytes, startPos)
                
                if endPos != -1:
                    # Write HTML before placeholder
                    self.wfile.write(htmlBytes[startPos:endPos])
                    # Write the data
                    self.wfile.write(replacementStr.encode('utf-8'))
                    return endPos + len(phBytes) # Return new start position
                return startPos # If not found, just return old pos
            
            currentPos = 0
            
            # 4. INJECT DATA
            currentPos = injectChunk(currentPos, "VAR_LEVEL", str(gal))
            currentPos = injectChunk(currentPos, "VAR_PERCENT", percent)
            currentPos = injectChunk(currentPos, "VAR_STATUSWELL", pumpOnStr)
            currentPos = injectChunk(currentPos, "VAR_STATUSHOUSE", str(isHousePumpOn()))
            currentPos = injectChunk(currentPos, "VAR_TIME_LEFT_RESET", str(timeLeftReset))
            currentPos = injectChunk(currentPos, "VAR_TIME", timeStr)
            
            for j in [[1440,2,24],[4320,6,72],[10080,15,168]]:
                dataList = []
                step = j[1]
                
                lastDataPoint = (tRPointer - 1) % 10080
                
                if lastDataPoint >= j[0]:
                    for i in range(lastDataPoint - j[0], lastDataPoint, step):
                        dataList.append("{:.1f}".format(tankReadingsRecord[i]))
                else:
                    for i in range((len(tankReadingsRecord) - (j[0] - lastDataPoint)), len(tankReadingsRecord), step):
                        dataList.append("{:.1f}".format(tankReadingsRecord[i]))
                    for i in range(0, lastDataPoint, step):
                        dataList.append("{:.1f}".format(tankReadingsRecord[i]))
                
                dataString = ",".join(dataList)
                currentPos = injectChunk(currentPos, f"VAR_DATA_{j[2]}", dataString)
    
            currentPos = injectChunk(currentPos, "VAR_CURRENT_SETTINGS", json.dumps(settingsOptions))
            currentPos = injectChunk(currentPos, "VAR_STATUSWELL", pumpOnStr)
            currentPos = injectChunk(currentPos, "VAR_TIME_LEFT_RESET", str(timeLeftReset))

            # Write the rest of the HTML file
            self.wfile.write(htmlBytes[currentPos:])

    def do_POST(self):
        if self.path == '/save_setting':
            contentLength = int(self.headers.get('Content-Length', 0))
            postData = self.rfile.read(contentLength)
            
            try:
                data = json.loads(postData)
                settingId = data.get('id')
                newValue = data.get('value')

                global settingsOptions
                index = settingId - 1
                
                if 0 <= index < len(settingsOptions):
                    settingsOptions[index] = newValue
                    saveSettings()

                self.sendResponse(200)
                self.sendHeader('Content-type', 'application/json')
                self.endHeaders()
                self.wfile.write(json.dumps({"status": "success"}).encode())
                
            except Exception as e:
                print("POST Error:", e)
                self.sendResponse(400)
                self.endHeaders()

    def sendCsv(self):
        try:
            BIN = 'tank_data.bin'
            
            csvFilename = "tank_data.csv"
            recordSize = 16
            
            fSize = os.stat(BIN)[6]
            if fSize >= recordSize:
                with open(BIN, 'rb') as f:
                    f.seek(fSize - recordSize)
                    rec = f.read(recordSize)
                    # Unpack just the date parts
                    _, _, yr, mon, day, _, _, _, _, _, _ = struct.unpack('<HHBBBBBHBHH', rec)
                    csvFilename = f"tank_data_{mon}_{day}_{yr+2000}.csv"

            # 2. Send Headers
            self.sendResponse(200)
            self.sendHeader('Content-type', 'text/csv')
            self.sendHeader('Content-Disposition', f'attachment; filename="{csvFilename}"')
            self.endHeaders()

            # 3. Stream Data directly to socket (Save RAM & no temp file)
            headerRow = "Month, Day, Year, Low, High, Low Hour, High Hour, Tank Fill, Fill Confidence, Tank Reading at Record Time, Tank Filling Time\n"
            self.wfile.write(headerRow.encode())
            
            with open(BIN, 'rb') as fBIN:
                while True:
                    data = fBIN.read(16)
                    if not data or len(data) != 16:
                        break
                    
                    minGal, maxGal, yr, mon, day, tMin, tMax, filled, conf, curr, fillT = struct.unpack('<HHBBBBBHBHH', data)
                    
                    # Format row
                    s = f"{mon}, {day}, {yr + 2000}, {minGal}, {maxGal}, {tMin/10:0.1f}, {tMax/10:0.1f}, {filled}, {conf / 255:0.1f}, {curr}, {fillT*6}\n"
                    self.wfile.write(s.encode())

        except Exception as e:
            print("CSV Error:", e)

    def sendMetadata(self):
        """Sends a description file."""
        try:
            self.sendResponse(200)
            self.sendHeader('Content-type', 'text/plain')
            self.sendHeader('Content-Disposition', 'attachment; filename="tank_data_metadata.txt"')
            self.endHeaders()
            
            with open('tank_data_metadata.txt', "rb") as f:
                self.wfile.write(f.read())
                
        except Exception as e:
            self.sendError(500, "Metadata Error")

    def sendJsonData(self):
        """Reads a batch of records from the END of the file backwards."""
        try:
            BIN = 'tank_data.bin'
            BATCH_SIZE = 100 
            fmt = '<HHBBBBBHBHH'
            recordSize = struct.calcsize(fmt)
            
            try:
                os.stat(BIN)
            except OSError:
                self.sendError(404, "Data file not found")
                return

            # 1. Parse Query Params
            query = self.path.split('?')[-1]
            params = {}
            if '=' in query:
                for p in query.split('&'):
                    if '=' in p:
                        k, v = p.split('=')
                        try:
                            params[k] = int(v)
                        except:
                            pass
            
            batchIndex = params.get('batch_index', 0)
                
            # 2. File Metrics
            fileSize = os.stat(BIN)[6]
            totalRecords = fileSize // recordSize
            
            # 3. Calculate Offset
            startRecord = totalRecords - ((batchIndex + 1) * BATCH_SIZE)
            
            recordsToRead = BATCH_SIZE
            
            if startRecord < 0:
                recordsToRead = BATCH_SIZE + startRecord
                startRecord = 0
            
            startByte = startRecord * recordSize

            # 4. Read Batch
            records = []
            prevCurr = 0
            
            if recordsToRead > 0:
                with open(BIN, "rb") as f:
                    f.seek(startByte)
                    
                    # Read chunk into memory (faster than many small reads)
                    chunk = f.read(recordsToRead * recordSize)
                    
                    for i in range(0, len(chunk), recordSize):
                        data = chunk[i:i+recordSize]
                        if len(data) != recordSize: break
                        
                        minGal, maxGal, yr, mon, day, tMin, tMax, filled, conf, curr, fillT = struct.unpack(fmt, data)
                        fillT *= 6

                        h, m, s = "hrs", "mins", "secs"
                        if fillT%60 <= 1: s = "sec"
                        if (fillT%3600)//60 <= 1: m = "min"
                        if fillT//3600 <= 1: h = "hr"
                            
                        if fillT >= 3600:
                            fillTStr = f"{fillT//3600} {h} {(fillT%3600)//60} {m} {fillT%60} {s}"
                        elif fillT >= 60:
                            fillTStr = f"{fillT//60} {m} {fillT%60} {s}"
                        else:
                            fillTStr = f"{fillT%60} {s}"
                        
                        lowMins = (tMin // 10) * 60 + (tMin % 10) * 6
                        highMins = (tMax // 10) * 60 + (tMax % 10) * 6
                        
                        records.append({
                            "date": f"{mon}/{day}/{yr+2000}",
                            "low": minGal, "high": maxGal,
                            "timeLow": f"{tMin//10:02d}:{(tMin%10)*6:02d}", 
                            "timeHigh": f"{tMax//10:02d}:{(tMax%10)*6:02d}",
                            "timeLowMins": lowMins,
                            "timeHighMins": highMins,
                            "fillTimeSecs": fillT,
                            "filled": filled, "conf": f"{conf/255*100:.1f} %",
                            "change": curr - prevCurr, "usage": (filled - (curr - prevCurr)),
                            "reading": curr, "fillTime": fillTStr,
                            "flow": f"{filled/(fillT/60):0.2f}" if fillT > 0 else "0.00"
                        })
                        
                        prevCurr = curr

            # 5. Send JSON
            response = {
                "data": records,
                "total": totalRecords,
                "batch_size": len(records)
            }
            
            self.sendResponse(200)
            self.sendHeader('Content-type', 'application/json')
            self.endHeaders()
            self.wfile.write(json.dumps(response).encode())

        except Exception as e:
            print("JSON Data Error:", e)
            self.sendError(500, "Server Error")
        
    def sendDataInfo(self):
        """Sends only the total number of records available."""
        try:
            BIN = 'tank_data.bin'
            fmt = '<HHBBBBBHBHH'
            record_size = struct.calcsize(fmt)
            
            if BIN not in os.listdir():
                self.sendError(404, "Data file not found")
                return
            
            total_records = os.stat(BIN)[6] // record_size
            
            self.sendResponse(200)
            self.sendHeader('Content-type', 'application/json')
            self.endHeaders()
            self.wfile.write(json.dumps({"total": total_records}).encode())
            
        except Exception as e:
            self.sendError(500, "Server Error")

NTP_HOST = "time.google.com" 
NTP_DELTA = 2208988800 

def dayOfWeek(y, m, d):
    # Method to find the day of the week (0=Sunday, 1=Monday...6=Saturday).
    t = [0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4]
    if m < 3:
        y -= 1
    return (y + y//4 - y//100 + y//400 + t[m-1] + d) % 7

def getNthSunday(year, month, n):
    # Finds the date of the nth Sunday in a given month/year.
    count = 0
    # Check days 1 through 31
    for day in range(1, 32):
        # Check if this day is a Sunday (0)
        if dayOfWeek(year, month, day) == 0:
            count += 1
            if count == n:
                return day
    return 0

def isPdt(year, month, day, hourUtc):
    """
    Determines if current UTC time falls within US DST (Pacific Daylight Time).
    DST: 2nd Sunday March -> 1st Sunday November.
    """
    # Get the switch days for this year
    startDay = getNthSunday(year, 3, 2)  # 2nd Sunday March
    endDay   = getNthSunday(year, 11, 1) # 1st Sunday November
    
    # 1. Quick Checks based on Month
    if 4 <= month <= 10:       # April to October is definitely DST
        return True
    if month == 12 or month < 3: # Dec, Jan, Feb are definitely Standard
        return False

    # 2. Check Transition Months (March and November)
    
    # MARCH CHECK
    if month == 3:
        if day < startDay:
            return False # Before the switch
        if day > startDay:
            return True  # After the switch
        # If it IS the 2nd Sunday (startDay):
        # Switch happens at 2am Local = 10:00 UTC
        if hourUtc < 10:
            return False
        else:
            return True

    # NOVEMBER CHECK
    if month == 11:
        if day < endDay:
            return True  # Before the switch
        if day > endDay:
            return False # After the switch
        # If it IS the 1st Sunday (endDay):
        # Switch happens at 2am Local = 09:00 UTC (because we are in PDT/UTC-7)
        if hourUtc < 9:
            return True
        else:
            return False
            
    return False

def syncRtc():
    """Syncs Pico time via NTP and auto-adjusts for Oregon DST."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        ntpPacket = b'\x1b' + 47 * b'\x00'
        
        # Resolve IP
        addr = socket.getaddrinfo(NTP_HOST, 123)[0][-1]
        s.sendto(ntpPacket, addr)
        
        data, _ = s.recvfrom(1024)
        s.close()
        
        # Calculate UTC Unix Time
        ntpTime = struct.unpack('!I', data[40:44])[0]
        unixTime = ntpTime - NTP_DELTA
        
        # Get UTC Time Components
        tmUtc = time.gmtime(unixTime)
        year, month, day = tmUtc[0], tmUtc[1], tmUtc[2]
        hourUtc = tmUtc[3]
        
        # Check if we are in PDT or PST
        if isPdt(year, month, day, hourUtc):
            offset = -7 * 3600 # PDT
        else:
            offset = -8 * 3600 # PST
            
        # Calculate Local Time
        localUnix = unixTime + offset
        tmLocal = time.gmtime(localUnix)
        
        rtc.datetime((tmLocal[0], tmLocal[1], tmLocal[2], tmLocal[6] + 1, 
                      tmLocal[3], tmLocal[4], tmLocal[5], 0))
        
        print(f"Time set: {time.localtime()}")
        return True

    except Exception as e:
        print(f"Sync failed: {e}")
        return False

def setup_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('', 80))
    s.listen(5)
    s.setblocking(False) 
    return s

def handleServerRequest(s):
    if s is None: return
    conn = None
    try:
        conn, addr = s.accept()
        conn.settimeout(1) # Small timeout for the request processing
        handler = wifiHandler(conn)
        handler.handleOneRequest()
        conn.close()
    except OSError as e:
        # EAGAIN means "No data available" - this is normal for non-blocking
        if e.args[0] not in (errno.EAGAIN, errno.ETIMEDOUT):
            print("Socket Error:", e)
    except Exception as e:
        print("Handler Error:", e)
    finally:
        if conn:
            conn.close()

wlan = network.WLAN(network.STA_IF)
wlan.active(True)

internetConnected = False
timeSynced = False
serverSocket = None

lastWifiAttempt = time.ticks_add(time.ticks_ms(), -10000)
lastTimeCheck = time.ticks_ms()

timer = time.ticks_ms()
frame = 0

while True:  
    # 1. WIFI MONITORING
    if not wlan.isconnected():
        # If WERE connected, but are now disconnected:
        if internetConnected:
            internetConnected = False
            timeSynced = False

            if serverSocket:
                try:
                    serverSocket.close()
                except:
                    pass
                serverSocket = None
        
        # Retry connection every 10 seconds
        if time.ticks_diff(time.ticks_ms(), lastWifiAttempt) > 10000:
            lastWifiAttempt = time.ticks_ms()
            wlan.connect(ssid, password)
            
            # Force garbage collection on reconnect to clear any fragmented memory
            gc.collect()
     
    else:
        # 2. WIFI CONNECTED LOGIC
        if not internetConnected:
            internetConnected = True
            ip, subnet, gateway, _ = wlan.ifconfig()
            wlan.ifconfig((ip, subnet, gateway, "8.8.8.8"))
            lastTimeCheck = time.ticks_add(time.ticks_ms(), -8000)
            if serverSocket is None:
                serverSocket = setup_server()
    
    # 3. TIME SYNC LOGIC
    if internetConnected and not timeSynced:
        if time.ticks_diff(time.ticks_ms(), lastTimeCheck) > 10000:
            lastTimeCheck = time.ticks_ms()
            if syncRtc():
                timeSynced = True
                highLowPrevious = loadHighLow()

                # If the loaded data is relavent for today, then keep it
                if highLowPrevious != None:
                    high, low, tankTimeFill, timestampMin, timestampMax, tankFill24Hours = highLowPrevious
                    high, low, tankTimeFill, timestampMin, timestampMax = int(high), int(low), int(tankTimeFill), float(timestampMin), float(timestampMax)
                    tempH, tempL = high, low
                
                # Set tRPointer to the correct point in time
                if loadedTankReadings and time.ticks_diff(time.ticks_ms(), startupTime) < 43200000:
                    oldTRPointer = tRPointer
                    dayAdjustment = tRPointer // 1440 * 1440
                    tRPointer = secondsFM() // 60
                    tRPointer += dayAdjustment
                    tRPointer %= 10080
                    tRPointer = int(tRPointer)
                    tRCounter = tRSum = 0
                    tankReadingsTimer = time.ticks_ms()
                    level = gallonsInTank()
                    if tRPointer > oldTRPointer:
                        for i in range(oldTRPointer, tRPointer):
                            tankReadingsRecord[i] = level
                    
                else:
                    tRPointer = secondsFM() // 60
                    tRCounter = tRSum = 0
                    level = round(gallonsInTank(),1)
                    tankReadingsRecord = array.array('f', [level] * 10080)

    # 4. WEB SERVER LOGIC
    if serverSocket and wlan.isconnected(): # Double check WiFi is still up
        handleServerRequest(serverSocket)
    
# Intial turn on when the screen is off, display regular status
    if buttonSelection == "off":
        if getStableValue(button1) and not button1Pressed:
            button1Pressed = True
            screenOn, buttonSelection = displayStatus()
        
        if getStableValue(button2) and not button2Pressed:
            button2Pressed = True
            screenOn, buttonSelection = displayStatus()
        
        if getStableValue(button3) and not button3Pressed:
            button3Pressed = True
            screenOn, buttonSelection = displayStatus()
        
        if getStableValue(button4) and not button4Pressed:
            button4Pressed = True
            screenOn, buttonSelection = displayStatus()
    
    # Main menu, shows status and allows to go to other screens
    if buttonSelection == "status":
        if getStableValue(button1) and not button1Pressed:
            button1Pressed = True
            lcdInit()
            timeLeftReset = ((dryWellResetTime + 180000) - time.ticks_diff(time.ticks_ms(), dryWellTime)) / 60000
            screenOn, buttonSelection = displayStatus(True, round(timeLeftReset))
        
        if getStableValue(button2) and not button2Pressed:
            button2Pressed = True
            displayOverallChange(settingsOptions[3])
            screenTimeout, buttonSelection = 10000, "trends"
            
        if getStableValue(button3) and not button3Pressed:
            button3Pressed = True
            historyRange = displayRecords(tankRecords, high, low, 0)
            screenTimeout, buttonSelection = 10000, "history"
            
        if getStableValue(button4) and not button4Pressed:
            button4Pressed = True
            displaySettings(settings, 0)
            screenTimeout, buttonSelection = 10000, "settings"
    
    # Displays the trends, and can pick between the two
    if buttonSelection == "trends":
        if getStableValue(button2) and not button2Pressed:
            button2Pressed = True
            displayOverallChange(settingsOptions[3]) 
        
        if getStableValue(button3) and not button3Pressed:
            button3Pressed = True
            displayDailyFill(settingsOptions[4]) 
        
        if getStableValue(button4) and not button4Pressed:
            button3Pressed = True
            buttonSelection = "off"
            lcdWrite(0x01)
    
    # Displays the tank records
    if buttonSelection == "history":
        if getStableValue(button1) and not button1Pressed:
            button1Pressed = True
            if historyRange == 0: historyRange = displayRecords(tankRecords, high, low, 0)
            else: historyRange = displayRecords(tankRecords, high, low, historyRange - 1)
            
        if getStableValue(button2) and not button2Pressed:
            button2Pressed = True
            historyRange = displayRecords(tankRecords, high, low, historyRange + 1)
            
        if getStableValue(button3) and not button3Pressed:
            button3Pressed = True
            historyFillRange = displayFillChange(tankRecords, 0)
            buttonSelection = "historyFill"
        
        if getStableValue(button4) and not button4Pressed:
            button4Pressed = True
            buttonSelection = "off"
            lcdWrite(0x01)
    
    if buttonSelection == "historyFill":
        if getStableValue(button1) and not button1Pressed:
            button1Pressed = True
            if historyFillRange == 0: historyFillRange = displayFillChange(tankRecords, 0)
            else: historyFillRange = displayFillChange(tankRecords, historyFillRange - 1)
        
        if getStableValue(button2) and not button2Pressed:
            button2Pressed = True
            historyFillRange = displayFillChange(tankRecords, historyFillRange + 1)
        
        if getStableValue(button3) and not button3Pressed:
            button3Pressed = True
            historyRange = displayRecords(tankRecords, high, low, 0)
            buttonSelection = "history"
        
        if getStableValue(button4) and not button4Pressed:
            button4Pressed = True
            buttonSelection = "off"
            lcdWrite(0x01)    
    
    # Opens and displays the settings menu
    if buttonSelection == "settings":
        if getStableValue(button1) and not button1Pressed:
            button1Pressed = True
            if selectedSettingIndex == 0: selectedSettingIndex = displaySettings(settings, 0)
            else: selectedSettingIndex = displaySettings(settings, selectedSettingIndex - 1)
        
        if getStableValue(button2) and not button2Pressed:
            button2Pressed = True
            selectedSettingIndex = displaySettings(settings, selectedSettingIndex + 1)
        
        if getStableValue(button3) and not button3Pressed:
            button3Pressed = True
            displaySettingsEdit(selectedSettingIndex)
            previousSetting = settingsOptions[selectedSettingIndex]
            screenTimeout, buttonSelection = 20000, "settingsEdit"
        
        if getStableValue(button4) and not button4Pressed:
            button4Pressed = True
            buttonSelection = "off"
            lcdWrite(0x01)
    
    # Shows after selecting a setting to edit
    if buttonSelection == "settingsEdit":
        if getStableValue(button1) and not button1Pressed:
            button1Pressed = True
            button1Timer = time.ticks_ms()
            if selectedSettingIndex <= 1:
                settingsOptions[selectedSettingIndex] -= 1
                if settingsOptions[selectedSettingIndex] < 0: settingsOptions[selectedSettingIndex] = 0
            elif selectedSettingIndex == 2:
                settingsOptions[selectedSettingIndex] -= 1
                if settingsOptions[selectedSettingIndex] < 5: settingsOptions[selectedSettingIndex] = 5
            elif selectedSettingIndex == 5:
                settingsOptions[selectedSettingIndex] -= 1
                if settingsOptions[selectedSettingIndex] < 0: settingsOptions[selectedSettingIndex] = 0
            elif selectedSettingIndex >= 3:
                settingsOptions[selectedSettingIndex][settingsTrendEdit] -= 1
                if settingsOptions[selectedSettingIndex][settingsTrendEdit] < 2: settingsOptions[selectedSettingIndex][settingsTrendEdit] = 2
            
            displaySettingsEdit(selectedSettingIndex)
        
        if getStableValue(button2) and not button2Pressed:
            button2Pressed = True
            button2Timer = time.ticks_ms()
            if selectedSettingIndex <= 1:
                settingsOptions[selectedSettingIndex] += 1
                if settingsOptions[selectedSettingIndex] > 2: settingsOptions[selectedSettingIndex] = 2
            elif selectedSettingIndex == 2:
                settingsOptions[selectedSettingIndex] += 1
                if settingsOptions[selectedSettingIndex] > 999: settingsOptions[selectedSettingIndex] = 999
            elif selectedSettingIndex == 5:
                settingsOptions[selectedSettingIndex] += 1
                if settingsOptions[selectedSettingIndex] > 100: settingsOptions[selectedSettingIndex] = 100
            elif selectedSettingIndex >= 3:
                settingsOptions[selectedSettingIndex][settingsTrendEdit] += 1
                if settingsOptions[selectedSettingIndex][settingsTrendEdit] > 99: settingsOptions[selectedSettingIndex][settingsTrendEdit] = 99
            
            displaySettingsEdit(selectedSettingIndex)
        
        if getStableValue(button3) and not button3Pressed:
            button3Pressed = True           
            if selectedSettingIndex == 3 or selectedSettingIndex == 4:
                settingsTrendEdit += 1
                if settingsTrendEdit == 3:
                    settingsTrendEdit = 0
                    saveSettings()
                    displaySettings(settings, selectedSettingIndex)
                    buttonSelection = "settings"
            else:
                saveSettings()
                displaySettings(settings, selectedSettingIndex)
                buttonSelection = "settings"
        
        if getStableValue(button4) and not button4Pressed:
            button4Pressed = True
            settingsOptions[selectedSettingIndex] = previousSetting
            settingsTrendEdit = selectedSettingIndex = 0
            buttonSelection = "off"
            lcdWrite(0x01)
            
        if getStableValue(button1) and time.ticks_diff(time.ticks_ms(), button1Timer) > 500:
            button1Timer = time.ticks_add(button1Timer,75)
            if selectedSettingIndex == 2:
                settingsOptions[selectedSettingIndex] -= 1
                if settingsOptions[selectedSettingIndex] < 5: settingsOptions[selectedSettingIndex] = 5
            if selectedSettingIndex == 5:
                settingsOptions[selectedSettingIndex] -= 1
                if settingsOptions[selectedSettingIndex] < 0: settingsOptions[selectedSettingIndex] = 0
            elif selectedSettingIndex >= 3:
                settingsOptions[selectedSettingIndex][settingsTrendEdit] -= 1
                if settingsOptions[selectedSettingIndex][settingsTrendEdit] < 2: settingsOptions[selectedSettingIndex][settingsTrendEdit] = 2
            displaySettingsEdit(selectedSettingIndex, numOnly = True)
        
        if getStableValue(button2) and time.ticks_diff(time.ticks_ms(), button2Timer) > 500:
            button2Timer = time.ticks_add(button2Timer,75)
            if selectedSettingIndex == 2:
                settingsOptions[selectedSettingIndex] += 1
                if settingsOptions[selectedSettingIndex] > 999: settingsOptions[selectedSettingIndex] = 999
            if selectedSettingIndex == 5:
                settingsOptions[selectedSettingIndex] += 1
                if settingsOptions[selectedSettingIndex] > 100: settingsOptions[selectedSettingIndex] = 100
            elif selectedSettingIndex >= 3:
                settingsOptions[selectedSettingIndex][settingsTrendEdit] += 1
                if settingsOptions[selectedSettingIndex][settingsTrendEdit] > 99: settingsOptions[selectedSettingIndex][settingsTrendEdit] = 99
            displaySettingsEdit(selectedSettingIndex, numOnly = True)
    
    # If button gets pressed, reset the screen timeout
    if button1Pressed or button2Pressed or button3Pressed or button4Pressed:
        clearLCD = time.ticks_ms()
    
    # Button resets
    if not getStableValue(button1): button1Pressed = False
    if not getStableValue(button2): button2Pressed = False
    if not getStableValue(button3): button3Pressed = False
    if not getStableValue(button4): button4Pressed = False
    
    # Screen timed out
    if time.ticks_diff(time.ticks_ms(), clearLCD) > screenTimeout and screenOn:
        if buttonSelection == "settingsEdit": settingsOptions[selectedSettingIndex] = previousSetting
        screenOn = False
        buttonSelection = "off"
        screenTimeout = 8000
        lcdWrite(0x01)
        
    if secondaryPumpSetting != 2:
        secondaryPumpOnOff.value(secondaryPumpSetting)
        if not secondaryPumpSettingSpeed:
            secondaryPumpSettingSpeed = True
            setPumpSpeed(settingsOptions[5])
        if wellPumpSetting == 2:
            wellPumpOnOff.value(0)
    else: secondaryPumpSettingSpeed = False

    if wellPumpSetting != 2:
        wellPumpOnOff.value(wellPumpSetting)
        if secondaryPumpSetting == 2:
            setPumpSpeed(0)
            secondaryPumpOnOff.value(0)    
        
    if time.ticks_diff(time.ticks_ms(), waterFlowCheckTimer) >= 100:
        waterFlowList, waterCurrentlyFlowing = waterFlowCheck(waterFlowList, waterCurrentlyFlowing)
        waterFlowCheckTimer = time.ticks_add(waterFlowCheckTimer, 100)
        
    shouldPump, tankFull = checkSensors(tankFull)
    # Checks if the sensors allow water to be pumped in (tank isn't full), if pumps are turned on (auto or on), and the well isn't dry    
    if shouldPump and wellPumpSetting == 2 and secondaryPumpSetting == 2:        
        # elapsedTime for cleaner formatting
        elapsedTime = time.ticks_diff(time.ticks_ms(), wellTurnOnGraceTime)
        
        if not wellDry:
            # Turn main well pump on
            wellPumpOnOff.value(1)
            
            # Wait 10 seconds to turn on secondary pump, can be adjsuted
            if not wellDryTimeJustEnded and elapsedTime > 10000:
                secondaryPumpOnOff.value(1)
                if turnOnSecondary:
                    turnOnSecondary = False
                    setPumpSpeed(settingsOptions[5])
            
            # Set a grace period timer to start monitoring wellDry status and turn on secondary pump
            if wellDryTimeJustEnded and isPumpOn():
                wellTurnOnGraceTime = time.ticks_ms()
                wellDryTimeJustEnded = False
                
            dryWellTime = time.ticks_ms() # Always updating until well runs dry
        
        # 15 seconds grace period after inital pump turn on to start monitoring wellDry status of the start stop relay, can be adjsuted
        # If the water hasn't started flowing after 60 seconds -- something is wrong and the pump determines a wellDry state, can be adjusted
        if not wellDryTimeJustEnded and ((not isPumpOn() and elapsedTime > 15000) or (not waterCurrentlyFlowing and elapsedTime > 60000)):
            wellDry = True 
            wellPumpOnOff.value(0) 
            secondaryPumpOnOff.value(0)

        if wellDry and time.ticks_diff(time.ticks_ms(), dryWellTime) > (dryWellResetTime + 180000): # Plus 3 minutes grace period
            wellDry = False
            wellDryTimeJustEnded = True
            wellTurnOnGraceTime = time.ticks_ms()
            turnOnSecondary = True
        
    # Tank is full or either pump set to off
    elif wellPumpSetting == 2 and secondaryPumpSetting == 2:
        wellDryTimeJustEnded = True
        wellPumpOnOff.value(0)
        setPumpSpeed(0)
        secondaryPumpOnOff.value(0)
    
    else:
        elapsedTime = 0

    # Run every 30 seconds to do a variety of tasks
    if time.ticks_diff(time.ticks_ms(), checkLowHighTimer) > 30000 and timeSynced:
        
        checkLowHighTimer = time.ticks_add(checkLowHighTimer, 30000)
        day, hour, minute = getTime(['d','h','min'])        
        
        # Check if it's time to reset (3 AM)
        if hour == 3 and minute == 0 and day != dayBefore:
            level = round(gallonsInTank())
            dayFill = 0
            overallConfidence = 0
            for i in tankFill24Hours:
                dayFill += i[0]
            for i in tankFill24Hours:
                overallConfidence += (i[0] / dayFill) * calculateConfidence(i[1])
            dayFill = round(dayFill)
            
            # If the pump isn't on, then save normally, otherwise, save the current data and try to save later
            if not isPumpOn():
                tankRecords.append(saveTankData(low, high, timestampMin, timestampMax, dayFill, overallConfidence, level, tankTimeFill))
                saveLaterList = []
                saveLater = False
                reSynctRPointer = True
                daysToReset += 1
                
            else:
                saveLaterList = [low, high, timestampMin, timestampMax, dayFill, overallConfidence, level, tankTimeFill]
                saveLater = True
            
            tankFill24Hours = [] # Reset this too, as it's a new 24 hours, and we just used everything in it
            tankTimeFill = 0
            high = low = tempH = tempL = level
            timestampMin = timestampMax = hour + round(minute/6)/10
            dayBefore = day
            
            if timeSynced:
                saveHighLow(high, low, timestampMin, timestampMax, tankFill24Hours, tankTimeFill)
        
        # Wait only 3 more hours until 6 AM, otherwise save data as was
        if saveLater and hour < 6:
            if tankFill24Hours: # A new addition was made -- it finished pumping into the well
                # Calculate the new dayFill, confidence, and tankTimeFill             
                yesterdayPortion = (10800 - pumpInStart) % 86400
                b = ((pumpInStop - pumpInStart) % 86400)
                yesterdayRatio = yesterdayPortion / (((pumpInStop - pumpInStart) % 86400)) # Reset happens at 10800, or 3 AM, not midnight

                adjustedFill = yesterdayRatio * tankFill24Hours[-1][0]
                adjustedConfidence = ((saveLaterList[4] / (saveLaterList[4] + adjustedFill)) * saveLaterList[5]) + ((adjustedFill / (saveLaterList[4] + adjustedFill)) * (tankFill24Hours[-1][1]))

                saveLaterList[4] += round(adjustedFill)
                saveLaterList[5] = adjustedConfidence
                saveLaterList[7] += yesterdayPortion

                tankRecords.append(saveTankData(*saveLaterList))

                # Change the last entry of tankFill24Hours to the updated part, containing only the data from today
                tankFill24Hours[-1][0] *= 1 - yesterdayRatio
                
                # Subtract yesterday's portion from tankTimeFill, since tankTimeFill gets added when the pump stopped, which was the next day
                tankTimeFill -= yesterdayPortion
                
                saveLaterList = []
                saveLater = False
                reSynctRPointer = True
                daysToReset += 1
                
        elif saveLater and hour == 6: # Too late, save as was
            tankRecords.append(saveTankData(*saveLaterList))
            saveLaterList = []
            saveLater = False
            reSynctRPointer = True
            daysToReset += 1
        
        # Instead of listing it 3 times after every tankRecords.append(), just have it here once
        if len(tankRecords) > 100:
            del tankRecords[0]
                
        # Re-sync the tRPointer every 3 AM to prevent drift
        if reSynctRPointer:
            reSynctRPointer = False
            syncRtc()
            oldTRPointer = tRPointer
            dayAdjustment = ((tRPointer + 720) // 1440) * 1440
            tRPointer = secondsFM() // 60
            tRPointer += dayAdjustment
            tRCounter = tRSum = 0
            tankReadingsTimer = time.ticks_ms()
            level = gallonsInTank()
            if tRPointer > oldTRPointer:
                for i in range(oldTRPointer, tRPointer):
                    tankReadingsRecord[i] = level
        
        # Restart Pico
        if daysToReset == 5:
            with open('temp_tankReadings.bin', 'wb') as f:
                f.write(struct.pack('<I', tRPointer))
                f.write(tankReadingsRecord)
            saveHighLow(high, low, timestampMin, timestampMax, tankFill24Hours, tankTimeFill)
            reset()
        
        # Update high/low
        level = round(gallonsInTank())
        if level > high:
            high = level
            timestampMax = hour + round(minute/6)/10
        if level < low:
            low = level
            timestampMin = hour + round(minute/6)/10
    
        if minute == 0: # See if temp save every hour, reduces writes to card
            if (high - tempH >= 5) or (tempL - low >= 5):
                tempH = high
                tempL = low
                
                if timeSynced:
                    saveHighLow(high, low, timestampMin, timestampMax, tankFill24Hours, tankTimeFill)
        
    # Read tank level every second
    if time.ticks_diff(time.ticks_ms(), tankReadingsTimer) >= 1000:
        tankReadingsTimer = time.ticks_add(tankReadingsTimer, 1000)
        tRSum += gallonsInTank() # tR = tankReading for formatting
        tRCounter += 1
        # Every 60 seconds average the data and append to the array of tank level
        if tRCounter == 60:
            tankReadingsRecord[tRPointer] = tRSum / 60
            tRPointer = (tRPointer + 1) % 10080
            tRCounter = tRSum = 0
                
        # For formatting:
        pumpingWater = getStableValue(secondaryPumpOnOff)
        housePumping = isHousePumpOn()
    
        # Figures out when the well pump started pumping, and if the house pump turned on during this time to muddy the data
        if pumpingWater and not recordedPumpOutStart:
            if housePumping:
                pumpOutStart = secondsFM()
                pumpOutStartGal = gallonsInTank()
                outOnBeforeIn = False
                recordedPumpOutStart = True
        elif pumpingWater and recordedPumpOutStart:
            if not housePumping:
                pumpOutStop = secondsFM()
                pumpOutStopGal = gallonsInTank()
                outOnAfterIn = False
                recordedPumpOutStart = False
        elif not pumpingWater:
            recordedPumpOutStart = False
        
        if pumpingWater and secondaryPumpWasOff:
            pumpInStart = secondsFM()
            pumpInStartGal = gallonsInTank()
            if housePumping:
                pumpOutStart = secondsFM()
                pumpOutStartGal = gallonsInTank() 
                outOnBeforeIn = True
                recordedPumpOutStart = True
            secondaryPumpWasOff = False 
        
        if pumpingWater and housePumping: pumpOutWhilePumpIn = True
        
        # Pump turned off and time to calcualte how much water was pumped in
        if not pumpingWater and not secondaryPumpWasOff:
            if housePumping:
                pumpOutStop = secondsFM()
                pumpOutStopGal = gallonsInTank()
                outOnAfterIn = True
                recordedPumpOutStart = False
            
            pumpInStop = secondsFM()
            pumpInStopGal = gallonsInTank()
            secondaryPumpWasOff = True
            tankRunTime = (pumpInStop - pumpInStart) % 86400
            
            if tankRunTime >= 120: #If pump was pumping more than 2 minutes, then record data, otherwise might be a fluke
                tankTimeFill += tankRunTime
                # If house pump was never turned on:
                if not pumpOutWhilePumpIn:
                    filled, ratioCleanOnData = calculatePartialFlow(pumpInStart, pumpInStop, tankRunTime, pumpInStartGal, pumpInStopGal)
                    
                else:
                    pumpOutWhilePumpIn = False

                    if outOnBeforeIn and outOnAfterIn: # House pump was on the whole time
                        filled, ratioCleanOnData = calculatePartialFlow(pumpInStart, pumpInStop, tankRunTime, pumpInStartGal, pumpInStopGal)
                        
                    elif outOnBeforeIn and not outOnAfterIn: # House pump started before well pump, but stopped before well pump stopped
                        filled, ratioCleanOnData = calculatePartialFlow(pumpOutStop, pumpInStop, tankRunTime, pumpOutStopGal, pumpInStopGal)
                    
                    elif not outOnBeforeIn and outOnAfterIn:  # House pump started after well pump, and finished after well pump stopped
                        filled, ratioCleanOnData = calculatePartialFlow(pumpInStart, pumpOutStart, tankRunTime, pumpInStartGal, pumpOutStartGal)
                    
                    elif not outOnBeforeIn and not outOnAfterIn: # House pump started after the well pump, and turned off before the well pump stopped
                        filled, ratioCleanOnData = calculatePartialFlow(pumpInStart, pumpOutStart, tankRunTime, pumpInStartGal, pumpOutStartGal, secondaryStart=pumpOutStop, secondaryStop=pumpInStop, secondaryStartGal=pumpOutStopGal, secondaryStopGal=pumpInStopGal)
                    
                    else: # Error... IDK
                        filled, ratioCleanOnData = 0, 0
                
                if filled != 0 and ratioCleanOnData != 0:
                    tankFill24Hours.append([filled, ratioCleanOnData])
                    if timeSynced:
                        tempH = high
                        tempL = low
                        saveHighLow(high, low, timestampMin, timestampMax, tankFill24Hours, tankTimeFill)
     
    if time.ticks_diff(time.ticks_ms(), timer) < 20*frame: # 50 fps
        rest = True
        while rest:
            time.sleep(0.005)
            if time.ticks_diff(time.ticks_ms(), timer) >= 20*frame:
                rest = False
    frame += 1
    if frame == 50:
        frame = 0
        timer = time.ticks_add(timer, 1000)
