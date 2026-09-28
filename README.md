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

The core firmware operates as a deterministic finite state machine (FSM), built to prevent rapid pump cycling, eliminate dry-run damage, and maintain continuous operational visibility.

#### 🛡️ Hardware Safety & Dry-Run Protection
* **Multi-Stage Low-Flow Detection:** Reads signals from the secondary Pico's signal-conditioning algorithm. If flow staggers below threshold during an active cycle, the system immediately trips a dry-well fault and cuts power to the well pump.
* **Cooldown & Recovery Timers:** Enforces a mandatory lockout period after a dry-well event, allowing the aquifer time to recover before re-attempting a fill cycle.
* **Over-Current & Thermal Cutoffs:** Monitors dry-run system and house pump amperage inputs to trip safety relays if motor currents exceed safe operational parameters.
* **Booster Pump Interlocking:** Prevents the pressure booster pump from running if the storage tank drops below minimum safe capacity, avoiding air-locking the household supply lines.

#### 📊 Optimized Storage & Telemetry
* **Binary File Logging (`.bin`):** Packs time-stamped fill cycles, pump runtimes, and system state transitions into a custom binary structure to minimize flash wear and maximize memory longevity on the Pico 2 W.
* **Dual-Interface Monitoring:** Serves real-time diagnostic telemetry through both an local 20x4 LCD display for immediate physical inspection and an embedded micro-web dashboard for local network control.
