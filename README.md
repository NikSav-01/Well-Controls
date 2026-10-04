# Robust Well Control

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
