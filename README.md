# Currently not usable working on getting it going soon bunch of changes coming after bugs are fixed

# ClusterCTRL GUI & System Health Monitor

A PyQt5 application that:

1. Controls ClusterHAT/ClusterCTRL (v2.x, v1.x, Single, Triple, A+6) boards, letting you power individual Pi nodes on/off and toggle extras (hub, LEDs, alert, write-protect).
2. Monitors “System Health” (CPU, RAM, network, temperature) on the controller Pi and (optionally) each attached node via SSH.

---

## Features

- **Board Selection**  
  Automatically detects which ClusterHAT/ClusterCTRL variant is attached (via `clusterctrl status`).  
  Supports:
  - ClusterHAT v2.x (4 nodes + hub/LED/alert/WP)
  - ClusterHAT v1.x (4 nodes + alert only)
  - ClusterCTRL Single (1 node)
  - ClusterCTRL Triple (3 nodes + hub/LED/alert)
  - ClusterCTRL A+6 (6 nodes + hub/LED/alert)

- **Node Power Control**  
  Check “P1 / P2 / …” and click **Power ON Selected** or **Power OFF Selected**. Internally runs `clusterctrl on pX` or `clusterctrl off pX`.

- **Extras (v2.x or compatible)**  
  Buttons to toggle:
  - **Hub** (on/off)  
  - **LED** (on/off) – the P1–P4 indicator LEDs  
  - **Alert** (on/off)  
  - **WP** (EEPROM write-protect on/off)

- **Live Status Pane**  
  Click **Refresh Status** to run `clusterctrl status` and see, e.g.:  
  ```
  P1=ON | P2=OFF | … | HUB=OFF | LED=ON | ALERT=OFF | WP=ON
  ```
  Each node also has a small red/green icon for instant visual feedback.

- **System Health Tab**  
  – **Local Controller Pi Stats** (auto-refresh every 5 seconds):  
   • CPU Usage (%)  
   • RAM Usage (%) & MiB used  
   • Temperature (via `vcgencmd`)  
   • Network I/O (sent/recv MiB)  
  – **Remote Node Stats (via SSH)**:  
   • For each node (P1, P2, …), runs (over SSH):  
    ```bash
    vcgencmd measure_temp
    python3 -c "import psutil; cpu=psutil.cpu_percent(interval=0.1); ram=psutil.virtual_memory().percent; net=psutil.net_io_counters(); print(f'{cpu:.1f},{ram:.1f},{net.bytes_sent//(1024*1024)},{net.bytes_recv//(1024*1024)}')"
    ```  
   • Displays “P1: CPU xx.x% | RAM yy.y% | Temp zz.z °C | Net ↑sent MiB ↓recv MiB”  
   • If unreachable/timeout, shows “Unreachable / Error.”

---

## Prerequisites

1. **Controller Pi** running Raspberry Pi OS (Bullseye or later).  
2. `clusterctrl` utility installed and in `$PATH` (default on ClusterHAT/CTRL images).  
   Test with:
   ```bash
   which clusterctrl
   clusterctrl status
   ```
3. **Python 3.7+** (should be installed by default).  
4. **PyQt5** & **psutil**  
   Either:
   ```bash
   sudo apt update
   sudo apt install python3-pyqt5 python3-psutil
   ```  
   or, if you prefer `pip`:
   ```bash
   pip3 install --user PyQt5 psutil
   ```
5. (For remote-node health stats) **Passwordless SSH** from controller Pi → each node (e.g. `pi@p1.local`, `pi@p2.local`, …).  
   - Generate an SSH key (if you haven’t already):
     ```bash
     ssh-keygen -t rsa -b 4096
     ```  
   - Copy the public key to each node:
     ```bash
     ssh-copy-id pi@p1.local
     ssh-copy-id pi@p2.local
     …etc.
     ```  
   - Test with:
     ```bash
     ssh pi@p1.local echo OK
     ```
6. Ensure the two icon files (`icons/icon_green.png`, `icons/icon_red.png`) are present in the repository.

---

## Installation

You have two basic options:

### A) One-liner (recommended)

On your controller Pi, run:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/gam3t3chelectronicshobbyhouse/clusterctrlgui/main/install.sh)"
```

This will:
1. Download and run `install.sh` from this repository.
2. Install PyQt5/psutil via `apt` and set execute permission on `clusterctrl_gui.py`.

After the script completes, launch the GUI:

```bash
cd clusterctrlgui
./clusterctrl_gui.py
```
## Uninstall One-liner
```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/gam3t3chelectronicshobbyhouse/clusterctrlgui/main/uninstall.sh)"
```

### B) Manual (clone + install)

1. **Clone the repo**:  
   ```bash
   git clone https://github.com/gam3t3chelectronicshobbyhouse/clusterctrlgui.git
   cd clusterctrlgui
   ```

2. **Install dependencies**:  
   ```bash
   sudo apt update
   sudo apt install -y python3-pyqt5 python3-psutil
   ```  
   _or via pip:_  
   ```bash
   pip3 install --user PyQt5 psutil
   ```

3. **Make it executable**:  
   ```bash
   chmod +x clusterctrl_gui.py
   ```

4. **Run**:  
   ```bash
   ./clusterctrl_gui.py
   ```

---

## Usage

1. **Control Tab** (default)  
   - Select your board version in the top dropdown (e.g., "ClusterHAT v2.x").  
   - Check one or more “P1 / P2 / …” boxes.  
   - Click **Power ON Selected** or **Power OFF Selected**.  
   - If your board supports it (e.g., v2.x or Triple/A+6), you’ll see buttons to toggle **Hub**, **LED**, **Alert**, and **WP**.  
   - Click **Refresh Status** to update node icons (green=ON, red=OFF) and the summary line.

2. **System Health Tab**  
   - Shows local CPU, RAM, Temp, and Network stats (auto refresh every 5 s).  
   - Below that, for each node (P1..P4 or P1..P6, depending on your board), displays:  
     ```
     P1: CPU xx.x% | RAM yy.y% | Temp zz.z °C | Net ↑sent MiB ↓recv MiB
     ```  
   - Click **Refresh Health Stats** to force an immediate update (includes SSH calls to each node).  
   - If a node is unreachable or SSH times out, that line reads:  
     ```
     P3: Unreachable / Error
     ```

---

## Customization

- To **add support** for a new ClusterCTRL variant, create a new subclass of `BoardDefinition` in `clusterctrl_gui.py` and add it to `_detect_and_populate_boards()`.  
- To **change the auto-refresh interval** for local stats, edit:
  ```python
  self.health_timer.setInterval(5000)  # milliseconds
  ```
- To **collect additional data** (e.g. disk usage or GPU clock), extend `_update_local_stats()` or the SSH one-liner in `_update_remote_stats()`:
  - For GPU clock:
    ```bash
    vcgencmd measure_clock gpu
    ```
  - For disk I/O:
    ```python
    psutil.disk_io_counters()
    ```

---

## Troubleshooting

- **`clusterctrl` not found**:  
  Ensure you’re running on a Pi with ClusterHAT/CTRL support.  
  ```bash
  which clusterctrl
  ```
- **SSH errors for remote nodes**:  
  Verify:  
  ```bash
  ssh pi@p1.local echo OK
  ```  
  If it still prompts for a password, re-run `ssh-copy-id pi@p1.local` until no passphrase is needed.
- **psutil module missing**:  
  If `import psutil` fails, run:
  ```bash
  sudo apt install python3-psutil
  ```  
  _or:_  
  ```bash
  pip3 install --user psutil
  ```

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
