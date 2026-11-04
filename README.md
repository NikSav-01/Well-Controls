**Custom automated dual-pump control and monitoring system built on Raspberry Pi Pico 2 W.**

---

### System Purpose & Core Objectives

This system automates water transfer from a low-yield well into a residential storage tank for household use. It coordinates two pumps, prevents dry-run pump damage, and tracks well recovery and water usage performance over time.

* **Dual-Pump Automation:** Controls both the well pump and booster pump while enforcing safety cut-offs to prevent the well pump from running dry.
* **Tank Level Management:** Tracks tank capacity in real time to keep household water at maximum capacity without overfilling or cycling pumps unnecessarily.
* **Onsite & Remote Interfaces:** Features a local 20x4 character LCD display for immediate status checks alongside a lightweight web dashboard hosted on the Pico 2 W for remote monitoring.
* **Data & Trend Logging:** A lightweight web page hosted on the Pico displays fill and usage patterns, storing data in space-efficient format of .bin for maximum longevity.

### System Architecture

![System Architecture Diagram](assets/system-architecture.svg)

### Key Features & Safety Logic

#### Hardware Safety & Dry-Run Protection
* **Dry-well Protection** The secondary Pico reads flow data from the well line, filtering out noise and outliers to confirm true flow stagnation. Simultaneously, motor amperage is monitored to catch sudden drops in load resistance when the pump loses prime. Combining both inputs ensures all dry-well events are caught immediately, cutting power to both pumps to prevent mechanical damage.
* **Recovery Lockout:** An adjustable lockout timer starts after a dry-well event, giving the aquifer time to recover before re-attempting a fill cycle.
* **Grace Period:** Allows a short grace period upon pump startup before starting dry-well monitoring, giving pumps time to prime and establishing baseline flow and current readings.
* **Set/Reset Sensors:** Uses two tank level sensors in a set/reset configuration to prevent rapid cycling every time the water level fluctuates near the maximum level sensor.

#### Displays & Optimized Storage
* **On-Site Display:** A local 20x4 LCD display and a 4-button navigation array provide immediate feedback on tank capacity, active pump states, and daily fill/usage averages. Includes manual overrides for pump control, motor speed, and the dry-well recovery timer.
* **Web Dashboard:** A lightweight web page hosted directly on the Pico 2 W featuring real-time water level graphs, full daily data spreadsheets, and remote system configuration options, similar to the on-site display.
* **Long-term Data Retention:** Packs daily timestamped min/max tank levels, fill volumes, usage rates, and total pump runtimes into a custom binary (.bin) structure to minimize flash memory wear and stretch storage across the Pico 2 W's 4 MB flash memory.
* **Short-term Data Retention:** Maintains high-resolution water level data in SRAM for 24-hour, 3-day, and 7-day web dashboard graphs. To save memory and network bandwidth on the Pico, data is transmitted as a compressed binary stream and unpacked in the browser for rendering, keeping in mind the 520 KB SRAM constraints of the Pico 2 W.
* **Scheduled Memory Management:** Monitors system states to execute a clean reboot every five days during dormant periods (when pumps are idle), clearing heap allocation and preventing memory fragmentation from the web server.

### Hardware Components

| Component | Specification / Model | Voltage / Interface  | System Role |
| :--- | :--- | :--- | :--- |
| Primary Controller | Raspberry Pi Pico 2 W | 3.3V Logic / Wi-Fi | Runs core FSM logic, hosts web dashboard, drives LCD, gathers telemetry |
| Secondary Controller | Raspberry Pi Pico | 3.3V GPIO | Filters flow meter pulses and feeds binary state to Pico 2 W |
| Tank Level Sensor | Hydrostatic Sensor (TL-136) | 0-4.33 PSI → 4–20 mA (24 V) | Converts hydrostatic pressure head in tank into a 4–20 mA current signal |
| Current-to-Voltage Convertor | CV Convertor Module (LY254) | 4–20 mA (24 V) → 0-3.3V ADC | Converts 4–20 mA sensor current to a 0–3.3V analog input for Pico 2 W ADC |
| Dry-Well Protection | Cycle Sensor (CS1PH1-2HP) | 240VAC Mains | Independent hardware monitor reading well pump current for dry-well protection |
| Well Run Monitor | Optocoupler Module (B0C73GGKHX) | 240VAC Line → 0/3.3V Logic | Detects line voltage from Cycle Sensor to inform Pico 2 W if well run signal is active |
| House Run Monitor | Optocoupler Module (B0C73GGKHX) | VFD Line → 0/3.3V Logic | Reads VFD line voltage to inform Pico when house pump is actively running |
| Tank Level Switches | Dual Float Switch Kit (LS-FLOAT-KIT) | 24VDC Dry Contact | High/Low water limit switches configured in a Set/Reset pattern |
| Float Switch Relay | 1-Channel Relay Module (AE14921a) | 0/24V → 0/3.3V Logic | Steps down 24V float switch signals to 3.3V Pico logic inputs |
| Flow sensor | Hall-Effect Sensor (YF-S402C) | GPM → 3.3V Pulses | Sends water flow pulses to secondary Pico for noise filtering |
| Navigation Switches | 6x6x5mm Tactile Switches | 3.3V Active-HIGH | Provides 4-button user input for local LCD menu navigation |
| Local Display | 20x4 Character LCD (B007) | 5V / I2C (PCF8574T Driver) | Displays real-time system state, tank statistics, and control menus |
| Well Relay (Stage 1) | 1-Channel Relay Module (RK-S1B4) | 0/3.3V Logic → 0/24VDC | Intermediary relay driven by Pico 2 W to trigger 24V high-power relay |
| Well Relay (Stage 2) | 1-Channel Relay Module (3-01-1810-24V) | 0/24VDC → 0/240VAC | High-voltage relay provides 240VAC mains power to well pump |
| Booster Pump Relay | 1-Channel Relay Module (RK-S1B4) | 0/3.3V Logic → 0/12VDC | Switches 12VDC power to booster pump motor driver |
| Pump Speed Controller | PWM Motor Driver (BTS7960B) | 3.3V PWM → 12V PWM | Regulates booster pump speed using a 16-bit PWM duty cycle |

### Signal Conditioning & Noise Immunity
Operates near a VFD and a pump motor, creating significant electromagnetic interference. To maintain reliable operation, key hardware and software signal conditioning controls were added:

Stronger Resistors: Utilizes external pull-down and pull-up resistors to sink ~0.2V of stray EMI voltage that bypassed the Pico's internal resistors.
RC Line Filtering: Combines a capacitor and pull-down resistor at the main Pico to form a low-pass filter, absorbing noise spikes and signal stuttering across the 30 ft data lines.
Software Sample Averaging: Uses a simple software filter to determine the true state of the pin by taking multiple consecutive readings and evaluating the majority result.

### Repository Structure
```
├── main.py                        # Primary Pico 2 W control loop (FSM, web server, telemetry, logging)
├── index.html                     # Web dashboard frontend hosted on Pico 2 W
├── settings.txt                   # System configuration constants
├── wifi.txt.example               # Template for local Wi-Fi credentials (SSID & Password)
├── tank_data.bin                  # Binary log file storing historical daily tank level, fill amounts, etc.
├── tank_data_metadata.txt         # Metadata file for tank_data.bin
├── temp_high_low.txt              # Temporary daily storage incase of unexpected power loss
├── secondary_main.py              # Secondary Pico main control loop
├── tools/
│   └── dome_calculation.py        # Offline numerical integration script for non-linear tank geometry
└── assets/
    ├── system-architecture.svg     # Rendered system architecture diagram
    ├── flowchart.mmd               # Mermaid source code for architecture diagram
    ├── dashboard-overview.png      # Screenshot of live telemetry dashboard
    └── dashboard-controls.png      # Screenshot of web control interface
```

### Script & File Overview
`main.py` (Primary Controller): Runs the main Finite State Machine on the Raspberry Pi Pico 2 W. Performs sensor reads, menu navigation, binary file logging, web server requests, and safety relay interlocks.
`secondary_main.py` (Secondary Controller): Runs on the remote Pico connected to the flow sensor. Filters hall-effect pulse streams, sending a clean binary flow signal to the primary Pico over a 30-foot data line.
`index.html`: Single-page web dashboard stored on the Pico 2 W filesystem, providing real-time telemetry graphs, status updates, and manual override controls.
`tools/DomeCalculation.py` (Offline Geometry Tool): Performs integration over the tank's complex upper dome and chimney geometry to calculate volume per 0.01 ft of water depth. Generated values above 6.3 ft are pre-defined in a lookup array to save ~20 seconds of boot time on the Pico 2 W.

Configuration & Storage Files:
* `settings.txt`: Stores changeable settings like pump states, pump speed, and well recovery delay.
* `wifi.txt.example`: Template containing network credentials (SSID/Password) for network connectivity.
* `tank_data.bin`: High-density, low-wear binary telemetry log file.
* `tank_data_metadata.txt`: Index and metadata tracking schema for `tank_data.bin`.
* `temp_high_low.txt`: Temporary daily file that prevents data loss if power drops before committing to `tank_data.bin`.
* `system-architecture.svg` & `flowchar.mmd`: Rendered SVG vector diagram and raw Mermaid source code.
