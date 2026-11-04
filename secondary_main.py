from machine import Pin
import time

led = Pin("LED", Pin.OUT)

# Init
for i in range(5):
    led.value(0)
    time.sleep(0.12)
    led.value(1)
    time.sleep(0.12)

flowPin = Pin(2, Pin.IN)
signalPin = Pin(3, Pin.OUT)
testPin = Pin(9, Pin.IN, Pin.PULL_UP)

# --- CONFIGURATION ---

# HYBRID TRIGGER SETTINGS
# Logic: If flow drops below (Baseline * RATIO) OR drops by (DELTA) pulses, start watching.
TRIGGER_RATIO = 0.65     # 65% of normal. Catches drastic crashes (120 -> 30)
TRIGGER_DELTA = 25       # 25 pulse drop. Catches summer/low-volume crashes (70 -> 45)

# TIMING SETTINGS
WATCH_SECONDS = 4        # How long flow must stay bad before shutting down. 
STARTUP_GRACE = 10       # Seconds after pump start before we begin monitoring (lets flow stabilize)
EMPTY_WELL_LIMIT = 12    # If flow stays below this for 10s, the well is truly empty (failsafe)
EMPTY_WELL_TIME = 4     # Time to enforce the limit above

# RESTART SETTINGS
RESTART_COOLDOWN = 30    # Seconds to wait after shutdown before trying again
RESTART_FLOW_REQ = 10    # Flow required to restart the pump
RESTART_DURATION = 3     # How many seconds of good flow needed to restart

# ----------------------

pulseCount = 0
pumpOff = True

# Lists to track history
# Track 30 seconds of history to create a stable "Baseline"
flowHistory = [0] * 30 

# State variables
dipStartTime = 0
inDipState = False
emptyWellStartTime = 0
offStartTime = time.time()
restartCounter = 0
pumpOnStartTime = 0

def interruptHandler(pin):
    global pulseCount
    pulseCount += 1
    
flowPin.irq(trigger=Pin.IRQ_FALLING, handler=interruptHandler)    

while True:
    if testPin.value() == 0:
        led.value(0)
        time.sleep(0.12)
        led.value(1)
    
    startCount = pulseCount
    time.sleep(1)
    pulsesPerSecond = pulseCount - startCount
    currentTime = time.time()
    
#     with open("data.txt", "a") as f: f.write(f'{pulsesPerSecond}\n')
#     print(pulsesPerSecond)
    
    # Always update history (even when pump is off to track background noise if any)
    flowHistory.append(pulsesPerSecond)
    if len(flowHistory) > 30:
        flowHistory.pop(0)
        
    # Calculate Baseline (Moving Average of last 30s)
    baseline = sum(flowHistory) / len(flowHistory)

    if not pumpOff:
        # --- PUMP RUNNING LOGIC ---

        # 1. Startup Grace Period
        # Don't check for dry well for the first 10 seconds after starting.
        # This prevents the initial surge from triggering a false dip.
        timeSinceStart = currentTime - pumpOnStartTime
        
        if timeSinceStart < STARTUP_GRACE:
            signalPin.value(1)
            # Debug
            print(f"Startup: PPS {pulsesPerSecond} | Base {baseline:.1f}")
            
        else:
            signalPin.value(1)
            
            # --- HYBRID DIP DETECTION ---
            # Condition A: Ratio Check (e.g., 120 -> 30)
            ratioCheck = pulsesPerSecond < (baseline * TRIGGER_RATIO)
            # Condition B: Delta Check (e.g., 70 -> 45)
            deltaCheck = (baseline - pulsesPerSecond) > TRIGGER_DELTA
            
            # If either condition is met, we enter a "Dip State"
            if ratioCheck or deltaCheck:
                if not inDipState:
                    inDipState = True
                    dipStartTime = currentTime
                    print(f"Dip Detected! Base: {baseline:.1f}, Curr: {pulsesPerSecond}")
            
            # If we are in a Dip State, check for Recovery
            if inDipState:
                # Recovery condition: Flow must be back to 90% of baseline (close to normal)
                if pulsesPerSecond > (baseline * 0.9):
                    inDipState = False # It was a glitch, cancel alarm
                
                # Shutdown condition: Stayed in dip for too long
                elif (currentTime - dipStartTime) > WATCH_SECONDS:
                    pumpOff = True
                    offStartTime = currentTime
                    signalPin.value(0)
            
            # --- EMPTY WELL SAFETY NET ---
            # Handles the fluctuating 10-20 scenario when the pump is sucking air
            if pulsesPerSecond < EMPTY_WELL_LIMIT:
                if emptyWellStartTime == 0:
                    emptyWellStartTime = currentTime
                elif (currentTime - emptyWellStartTime) > EMPTY_WELL_TIME:
                    pumpOff = True
                    offStartTime = currentTime
                    signalPin.value(0)
                    
            else:
                emptyWellStartTime = 0 # Reset timer if flow spikes up
                
            # Debug
            print(f"Run: PPS {pulsesPerSecond} | Base {baseline:.1f} | Dip: {inDipState} | Time: {currentTime - dipStartTime:.1f} | Signal State {signalPin.value()}")

    else:
        # --- PUMP OFF / RESTART LOGIC ---
        
        signalPin.value(0)
        inDipState = False # Reset dip state
        emptyWellStartTime = 0
        
        # Wait for cooldown
        if (currentTime - offStartTime) > RESTART_COOLDOWN:
            # Check for restart conditions
            if pulsesPerSecond > RESTART_FLOW_REQ:
                restartCounter += 1
            else:
                restartCounter = 0
            
            # If consistent flow found, turn on
            if restartCounter >= RESTART_DURATION:
                pumpOff = False
                pumpOnStartTime = time.time()
        
        else:
            restartCounter = 0
                
        # Debug
        print(f"Off: PPS {pulsesPerSecond} | Waiting: {currentTime - offStartTime:.1f} | Signal State {signalPin.value()}")
