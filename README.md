# Robust Well Control

**Custom automated dual-pump control and monitoring system built on Raspberry Pi Pico 2 W.**

---

### System Purpose & Core Objectives

This system automates water transfer from a low-yield well into a residential storage tank for household use. It coordinates two pumps, prevents dry-run pump damage, and tracks well recovery and water usage performance over time.

* **Dual-Pump Automation:** Controls both the well pump and booster pump while enforcing safety cut-offs to prevent the well pump from running dry.
* **Tank Level Management:** Tracks tank capacity in real time to keep household water at maximum capacity without overfilling or cycling pumps unnecessarily.
* **Onsite & Remote Interfaces:** Features a local 20x4 character LCD display for immediate status checks alongside a lightweight web dashboard hosted on the Pico 2 W for remote monitoring.
* **Data & Trend Logging:** A lightweight web page hosted on the Pico displays fill and usage patterns, storing data in space-efficient format of .bin for maximum longevity.

```mermaid
    flowchart LR
        %% Styling
    classDef mainPico fill:#0284c7,stroke:#0369a1,color:#fff,font-weight:bold
    classDef subPico fill:#0d9488,stroke:#0f766e,color:#fff,font-weight:bold

    subgraph Sensors ["Sensors & Inputs"]
        FM["Water Flow Meter"]
        FS["Tank Float Sensors <br/> (Set and Reset)"]
        LS["Hydrostatic Level Sensor"]
        CV["Current-to-Voltage Converter"]
        DRS["Amperage of Well Dry Run System"]
        HP["Amperage of House Pump"]
        BOSD["Buttons to Control On Site Display"]
        RM["Relay Module"]
    end

    subgraph Nodes ["Microcontrollers"]
        Pico2["Secondary Pico<br/><i>(30ft Remote Sensor Node)</i>"]:::subPico
        Pico1["Primary Pico 2 W<br/><i>(Main Controller & State Machine)</i>"]:::mainPico
    end

    subgraph Interfaces ["User Interfaces (Monitor and Control)"]
        LCD["On Site 20x4 Character LCD"]
        WEB["Pico 2 W Web Dashboard"]
    end

    subgraph Actuators ["Relays & Equipment"]
        R1[Well Pump Relay] --> P1[Well Pump]
        R2[Booster Pump Relay] --> P2[Booster Pump]
        PWM[PWM DC Motor Speed Controller] --> P2
    end

    %% Connections
    BOSD -->|HIGH/LOW| Pico1
    HP -->|HIGH/LOW| Pico1
    DRS -->|HIGH/LOW| Pico1
    LS -->|4-20 mA| CV
    CV -->|0-3.3V Analog| Pico1
    FM -->|Pulse Signal| Pico2
    Pico2 -->|GPIO HIGH/LOW<br/>Filtered Flow State| Pico1
    FS -->|24V HIGH/LOW| RM
    RM -->|3.3V HIGH/LOW| Pico1
    
    Pico1 <-->|Display Data| LCD
    Pico1 <-->|Wi-Fi| WEB
    Pico1 -->|HIGH/LOW| R1
    Pico1 -->|HIGH/LOW| R2
    Pico1 -->|16-bit PWM Duty Cycle| PWM
```

