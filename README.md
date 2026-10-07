# Serial & Ethernet Power Profiling

Multi-channel instrumentation and profiling suite for precision laboratory power meters (IeS ISW8001, MPM-1010). Designed for characterizing conversion efficiency, power factor, quiescent drain, and dynamic load transients on hardware such as **laboratory AC/DC battery chargers, switched-mode power supplies (SMPS), and DC-DC converters**.

Supports both native RS-232 serial interfaces and **Ethernet Serial-to-IP gateways (WIZnet WIZ750SR-110, Moxa)** to eliminate USB driver drops in lab testbenches.

### Laboratory Context: AC/DC Battery Charger Characterization
In a battery charging testbench, two synchronized meters measure the electrical boundaries simultaneously:
1. **Input Channel (AC Mains)**: Active power ($P_{\text{in}}$ in Watts), AC RMS voltage, AC RMS current, and Power Factor ($\text{PF}$).
2. **Output Channel (DC Battery Terminal)**: DC output power ($P_{\text{out}}$ in Watts), DC charging voltage, and DC current delivery.
3. **Live Conversion Metrics**:
   $$\text{Efficiency } \eta = \left(\frac{P_{\text{out, DC}}}{P_{\text{in, AC}}}\right) \times 100\% \qquad\qquad P_{\text{loss}} = P_{\text{in, AC}} - P_{\text{out, DC}}$$
All channels are time-synchronized, visualized in real time, and stream directly into structured CSV logs for automated test reporting and battery lifecycle analysis.

## Supported Devices

### ISW8001 (IeS Instruments Et Systemes)

**Connection:** RS232 via USB-to-Serial adapter

**Measurements:**
- Voltage, Current, Real Power, Reactive Power, Power Factor
- Configurable function (one measurement type at a time)
- Manual or automatic range control

**Sampling Rate:** ~2.1 Hz (470ms interval) in automatic mode

**Key Limitations:**
- Measures only one function at a time (switch between W, VAR, V, A, PF)
- Relatively slow sampling rate

**Protocol Documentation:** [docs/ISW8001-PROTOCOL.md](docs/ISW8001-PROTOCOL.md)

### MPM-1010 Series

**Connection:** RS232 via USB-to-Serial adapter

**Measurements:**
- Voltage, Current, Power, Power Factor, Frequency (all simultaneous)
- No range control (automatic)

**Sampling Rate (Serial Communication):** ~50 Hz with interrupt-after-power strategy

**Sampling Rate (Internal Updates):**
- Power measurements (V/I/W/PF): ~4 Hz (250ms intervals)
- Frequency: ~2.5 Hz (400ms intervals)

**Key Limitations:**
- Internal measurement updates are only 2.5-4 Hz despite fast serial communication
- Polling faster than ~10-20 Hz produces many duplicate readings

**Protocol Documentation:** [docs/MPM1010-PROTOCOL.md](docs/MPM1010-PROTOCOL.md)

## Installation

```bash
npm install
```

## Configuration

Configure the serial port via environment variable:

```bash
# For ISW8001
export ISW8001_PORT=/dev/tty.usbserial-110

# For MPM1010
export MPM1010_PORT=/dev/tty.usbserial-110

# Or use ISW8001_PORT for both (they can share the variable)
export ISW8001_PORT=/dev/tty.usbserial-110
```

Default port is `/dev/tty.usbserial-110`.

To find your serial port:
```bash
# macOS
ls /dev/tty.*

# Linux
ls /dev/ttyUSB*
```

### Optional Configuration

**Web server port:**
```bash
export PORT=2122  # Default is 2122
```

**Device type (for wattmeter-server.js):**
```bash
export WATTMETER_TYPE=mpm1010  # or isw8001 (default)
```

**Debug logging** (shows all serial commands and responses):
```bash
export DEBUG=1
```

## Usage

### Web Server Mode (Recommended)

Start the web server to continuously collect power data:

```bash
# ISW8001 (default)
node wattmeter-server.js

# MPM1010
WATTMETER_TYPE=mpm1010 node wattmeter-server.js
```

Then open http://localhost:2122/ in your browser to see:
- **Real-time power monitoring** with live charts
- **Statistics**: current, average, peak power, total energy
- **Additional measurements**: voltage, current, power factor, frequency (MPM1010 only)
- **Range information**: voltage/current ranges (ISW8001 only)
- **Export to Firefox Profiler** for detailed analysis with markers
- **CSV export** functionality

### Command Line Testing

**ISW8001:**
```bash
# Run comprehensive tests
npm test
# or
node test-isw8001.js

# Continuous monitoring (~470ms interval)
npm run test:continuous
# or
node test-isw8001.js --continuous

# Fast polling mode
npm run test:fast
# or
node test-isw8001.js --fast

# Send custom command
node test-isw8001.js --command "VOLT"     # Switch to voltage measurement
node test-isw8001.js --command "WATT"     # Switch to power measurement
node test-isw8001.js --command "PWF"      # Switch to power factor
node test-isw8001.js --command "STATUS?"  # Get device status
```

Press Ctrl+C to stop continuous or fast modes.

## Firefox Profiler Export

The web interface includes an "Open in Firefox Profiler" button that exports your power data in Firefox Profiler format.

**What's included:**
- **Power counter**: Energy consumption over time (picowatt-hours)
- **Voltage markers**: Voltage readings as an orange chart
- **Current markers**: Current readings as a red chart
- **Power factor markers**: Power factor readings as a blue chart (MPM1010 only)
- **Frequency markers**: Frequency readings as a grey chart (MPM1010 only)
- **Range change markers**: When voltage/current ranges change (ISW8001 only)
- **Debug timing markers**: Serial communication timing (MPM1010 only, for debugging)

This allows you to:
- Correlate power consumption with application behavior
- Compare power profiles from different test runs
- Analyze power spikes and their timing
- Export and share power measurement data

## Troubleshooting

### No data / connection issues

1. Check serial port path:
   ```bash
   ls /dev/tty.*  # macOS
   ls /dev/ttyUSB*  # Linux
   ```

2. Check permissions:
   ```bash
   # macOS
   sudo chmod 666 /dev/tty.usbserial-110

   # Linux - add user to dialout group
   sudo usermod -a -G dialout $USER
   # Then log out and back in
   ```

3. Enable debug mode to see communication:
   ```bash
   DEBUG=1 node wattmeter-server.js
   ```

### ISW8001 baud rate issues

The device supports 1200 or 9600 baud. If you changed the device baud rate:
1. Update `baudRate` in `isw8001.js` CONFIG section
2. The configured rate is shown briefly on device power-on

## Protocol Documentation

- [ISW8001 Protocol](docs/ISW8001-PROTOCOL.md)
- [MPM-1010 Protocol](docs/MPM1010-PROTOCOL.md)

---

## Python PowerProfiler Architecture (Multi-Device & Extensible)

The `powerprofiler` package provides an industrial, decoupled architecture for high-reliability lab testbenches and long running profiling:

```
[Meters / Transports]            [Supervisor Engine]            [Storage / WAL]          [Viewers / UI]
 ISW8001 (RS232/COM)   ───►  Worker Thread (Isolated) ───► SQLite WAL Database ───► Multi-Device Live GUI
 WIZ750SR (TCP/IP)     ───►  Worker Thread (Isolated) ───► (Single-Writer Lock)───► Live Efficiency Banner
 Demo Simulator        ───►  Worker Thread (Isolated) ───►                    ───► CSV & Profiler Export
```

### Key Architectural Strengths:
1. **Transport Abstraction**: Plug-and-play transports (`SerialTransport`, `TcpTransport`, `DemoTransport`). Easily extend to Modbus, VISA, or Bluetooth.
2. **Ethernet Serial-to-IP (WIZ750SR / Moxa)**: Direct native socket communication eliminates USB-serial driver instabilities (e.g. Prolific PL2303).
3. **Decoupled Producer-Consumer**: Workers run isolated threads with auto-reconnect and backoff. Data is stored in SQLite WAL mode so headless loggers and multiple GUI readers never lock each other.
4. **Automated Pairing & Live Efficiency**: Configure `role: "input"` and `role: "output"` with `pair: "OTHER-DEV"`; the system automatically computes and displays real-time conversion efficiency.

### Running the Python Suite & Quick Start

1. **One-Click Desktop Executable (No Terminal Needed)**:
   * Double-click **`ChargerPowerProfiler`** directly from your **Windows Desktop** (or run `dist/ChargerPowerProfiler/ChargerPowerProfiler.exe`).
   * Alternatively, double-click **`Run-Charger-Profiler.bat`** in the project root.
2. **Interactive GUI from Source**:
   ```bash
   python dual_wattmeter_gui.py
   ```
3. **Multi-Meter Headless Logger**:
   ```bash
   python -m powerprofiler.logger_app --config config/devices.wiznet.example.json
   ```
4. **Multi-Meter Live Dashboard (with Charts & Efficiency)**:
   ```bash
   python -m powerprofiler.gui.app --config config/devices.wiznet.example.json
   ```


---

## Graphical User Interface (GUI) Guide

The repository includes graphical interfaces tailored for real-time monitoring and charger testbench workflows:

### 1. Dual-Port Analyzer GUI (`dual_wattmeter_gui.py`)

Specifically built for paired AC-Input / DC-Output characterization of battery chargers and power converters.

#### Main Features:
* **Real-Time Efficiency Banner**:
  * Large, high-visibility status header displaying:
    $$\text{Efficiency } \eta = \left(\frac{P_{\text{out}}}{P_{\text{in}}}\right) \times 100\% \qquad\text{and}\qquad P_{\text{loss}} = P_{\text{in}} - P_{\text{out}}$$
  * Updates live with every incoming measurement cycle (~2.1 Hz).
* **Dual Channel Input Panels**:
  * **Channel 1 (AC Mains Input)**: Configured for $P_{\text{in}}$, RMS AC Voltage ($V$), RMS AC Current ($A$), and Power Factor ($\text{PF}$).
  * **Channel 2 (DC Battery Output)**: Configured for $P_{\text{out}}$, DC terminal Voltage ($V$), and DC Charging Current ($A$).
* **Mixed Connectivity per Port (Serial COM or Ethernet TCP)**:
  * Each channel has an independent dropdown to select:
    * `SERIAL (COM)`: Select any enumerated COM port (or click **↻** to rescan USB ports dynamically).
    * `ETHERNET (TCP)`: Enter the IP and port of the **WIZnet WIZ750SR-110** module (e.g. `192.168.1.150:5000`).
    * `SIMULATOR-P1 / P2`: Built-in mock hardware to test charting and efficiency without physical hardware attached.
* **Live Matplotlib Strip-Charts**:
  * Independent real-time strip charts auto-scale to display instantaneous power draw and dynamic charge step responses.
* **Data Export & Logging**:
  * **`▶ Start CSV Recording`**: Prompts for a filename and streams synchronized records directly to disk:
    `timestamp_iso, timestamp_epoch, p1_ac_volts, p1_ac_amps, p1_ac_watts, p1_ac_pf, p2_dc_volts, p2_dc_amps, p2_dc_watts, efficiency_pct, loss_watts`
  * **`💾 Save Snapshot to CSV`**: Exports an immediate tabular record of current operating metrics and conversion parameters.
* **Direct Instrument Controls**:
  * Switch meter measurement modes (`WATT`, `VAR`, `VOLT`, `AMP`, `PWF`) and toggles (`AutoRange` vs `Manual`) directly from the software without touching physical front panel buttons.

---

### 2. Multi-Meter Dashboard (`powerprofiler/gui/app.py`)

For multi-stage testbenches or multi-channel setups monitoring up to 8 wattmeters simultaneously:
* **High-Performance Blitting**: Uses Matplotlib canvas blitting to render up to 8 real-time graphs with minimal CPU overhead.
* **Spike Filtering Toggle**: Removes physical relay range-change transient spikes (known ISW8001 switching behavior).
* **Threshold Alerts**: Visual alerts with acknowledgement when voltage, power, or stale data limits are breached.
* **Paired System Efficiency**: Automatically discovers configured `input` and `output` pairings and displays conversion metrics across stages.

