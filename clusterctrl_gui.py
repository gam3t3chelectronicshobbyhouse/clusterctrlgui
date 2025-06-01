#!/usr/bin/env python3
"""
clusterctrl_gui.py

A PyQt5 GUI for controlling ClusterHAT/ClusterCTRL boards AND monitoring system
health (CPU/RAM/network/temperature) locally and on each Pi node via SSH.

This version includes:
  - Dropdown for selecting any supported board version (v2.x, v1.x, Single, Triple, A+6).
  - Fan On/Off buttons (maps to `clusterctrl fan on` / `clusterctrl fan off`).
  - Per-node On/Off buttons (e.g., “P1 On” / “P1 Off”, etc.) plus “All On” / “All Off”.
  - “Update from GitHub” only in the File menu, with safe handling of local changes.
  - System Health tab unchanged.
"""

import sys
import subprocess
import shlex
import os
import psutil
from functools import partial
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QMessageBox, QGroupBox, QTabWidget, QAction,
    QMenuBar, QGridLayout
)
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import Qt, QTimer

# --------------------------------------------------
# Utility functions
# --------------------------------------------------

def run_clusterctrl_command(args_list):
    """
    Run a `clusterctrl` command, return (return_code, stdout, stderr).
    """
    try:
        completed = subprocess.run(
            ["clusterctrl"] + args_list,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )
        return completed.returncode, completed.stdout.strip(), completed.stderr.strip()
    except FileNotFoundError:
        return -1, "", "clusterctrl not found; ensure it's installed and in PATH."

def parse_clusterctrl_status():
    """
    Call `clusterctrl status` and parse key/value lines into a dict.
    Returns: (status_dict, error_message)
    """
    rc, out, err = run_clusterctrl_command(["status"])
    if rc != 0:
        return None, f"Error running clusterctrl status: {err}"

    status = {}
    for line in out.splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        status[key.strip()] = val.strip()
    return status, None

def git_has_local_changes(repo_dir):
    """
    Returns True if 'git status --porcelain' is non-empty, indicating local changes.
    """
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        return bool(completed.stdout.strip())
    except subprocess.CalledProcessError:
        return False

# --------------------------------------------------
# BoardDefinition classes
# --------------------------------------------------

class BoardDefinition:
    name = "Unknown"
    supports_nodes = 0
    supports_hub_led = False
    supports_alert = False
    supports_wp = False

    @classmethod
    def valid_node_labels(cls):
        """
        Returns a list like ["p1","p2", ... up to supports_nodes].
        """
        return [f"p{i}" for i in range(1, cls.supports_nodes + 1)]

    @classmethod
    def command_power_on(cls, nodes):
        return ["on"] + nodes

    @classmethod
    def command_power_off(cls, nodes):
        return ["off"] + nodes

    @classmethod
    def command_all_on(cls):
        return ["on", "all"]

    @classmethod
    def command_all_off(cls):
        return ["off", "all"]

    @classmethod
    def command_hub_on(cls):
        return ["hub", "on"]

    @classmethod
    def command_hub_off(cls):
        return ["hub", "off"]

    @classmethod
    def command_led_on(cls):
        return ["led", "on"]

    @classmethod
    def command_led_off(cls):
        return ["led", "off"]

    @classmethod
    def command_alert_on(cls):
        return ["alert", "on"]

    @classmethod
    def command_alert_off(cls):
        return ["alert", "off"]

    @classmethod
    def command_wp_on(cls):
        return ["wp", "on"]

    @classmethod
    def command_wp_off(cls):
        return ["wp", "off"]

    @classmethod
    def command_fan_on(cls):
        return ["fan", "on"]

    @classmethod
    def command_fan_off(cls):
        return ["fan", "off"]

class ClusterHATv2(BoardDefinition):
    name = "ClusterHAT v2.x"
    supports_nodes = 4
    supports_hub_led = True
    supports_alert = True
    supports_wp = True

class ClusterHATv1(BoardDefinition):
    name = "ClusterHAT v1.x"
    supports_nodes = 4
    supports_hub_led = False
    supports_alert = True
    supports_wp = False

class ClusterCTRLSingle(BoardDefinition):
    name = "ClusterCTRL Single"
    supports_nodes = 1
    supports_hub_led = False
    supports_alert = False
    supports_wp = False

class ClusterCTRLTriple(BoardDefinition):
    name = "ClusterCTRL Triple"
    supports_nodes = 3
    supports_hub_led = True
    supports_alert = True
    supports_wp = False

class ClusterCTRLA6(BoardDefinition):
    name = "ClusterCTRL A+6"
    supports_nodes = 6
    supports_hub_led = True
    supports_alert = True
    supports_wp = False

# List of all supported board classes for the dropdown
ALL_BOARDS = [
    ClusterHATv2,
    ClusterHATv1,
    ClusterCTRLSingle,
    ClusterCTRLTriple,
    ClusterCTRLA6
]

# --------------------------------------------------
# Main Window
# --------------------------------------------------

class ClusterCtrlGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PiCluster Control & Monitoring")
        self.setGeometry(100, 100, 800, 550)

        # Current board definition
        self.current_board_def = None

        # --- Menubar & “File” menu ---
        menubar = QMenuBar(self)
        file_menu = menubar.addMenu("File")

        update_action = QAction("Update from GitHub", self)
        update_action.triggered.connect(self._perform_update)
        file_menu.addAction(update_action)

        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        self.setMenuBar(menubar)

        # --- Tabs ---
        self.tabs = QTabWidget()
        self.control_tab = QWidget()
        self.health_tab = QWidget()
        self.setCentralWidget(self.tabs)

        # --- Control‐tab widgets ---
        self.board_combo = QComboBox()
        self.node_buttons = {}        # e.g. {"p1": (btn_on, btn_off), ...}
        self.all_on_btn = QPushButton("All On")
        self.all_off_btn = QPushButton("All Off")
        self.hub_on_btn = QPushButton("Hub ON")
        self.hub_off_btn = QPushButton("Hub OFF")
        self.led_on_btn = QPushButton("LED ON")
        self.led_off_btn = QPushButton("LED OFF")
        self.alert_on_btn = QPushButton("Alert ON")
        self.alert_off_btn = QPushButton("Alert OFF")
        self.wp_on_btn = QPushButton("WP ON")
        self.wp_off_btn = QPushButton("WP OFF")
        self.fan_on_btn = QPushButton("Fan ON")
        self.fan_off_btn = QPushButton("Fan OFF")
        self.refresh_btn = QPushButton("Refresh Status")
        self.status_label = QLabel("Status: Unknown")

        # --- Health‐tab widgets (unchanged) ---
        self.local_cpu_lbl = QLabel("CPU Usage: N/A")
        self.local_ram_lbl = QLabel("RAM Usage: N/A")
        self.local_temp_lbl = QLabel("Temperature: N/A °C")
        self.local_net_lbl = QLabel("Network (sent/recv): N/A")
        self.remote_stat_labels = {}
        self.refresh_health_btn = QPushButton("Refresh Health Stats")

        self._build_control_tab()
        self._build_health_tab()

        self.tabs.addTab(self.control_tab, "Control")
        self.tabs.addTab(self.health_tab, "System Health")

        # Populate dropdown with all supported boards
        for bd in ALL_BOARDS:
            self.board_combo.addItem(bd.name, bd)

        # Set initial board selection to the first
        if self.board_combo.count() > 0:
            self.board_combo.setCurrentIndex(0)
            self._on_board_changed(0)

    # --------------------------------------------------
    # Build Control Tab UI
    # --------------------------------------------------
    def _build_control_tab(self):
        layout = QVBoxLayout()

        # Row 1: Board selection
        hb1 = QHBoxLayout()
        hb1.addWidget(QLabel("Select Board Version:"))
        hb1.addWidget(self.board_combo)
        layout.addLayout(hb1)

        # Row 2: Node control grid
        self.node_group = QGroupBox("Pi Node Controls")
        node_layout = QGridLayout()
        self.node_group.setLayout(node_layout)
        layout.addWidget(self.node_group)

        # Row 3: All On / All Off
        hb_all = QHBoxLayout()
        hb_all.addWidget(self.all_on_btn)
        hb_all.addWidget(self.all_off_btn)
        hb_all.addStretch()
        layout.addLayout(hb_all)

        # Row 4: Extras group (hub/led/alert/wp/fan)
        extras_group = QGroupBox("Extras")
        extras_layout = QHBoxLayout()
        extras_layout.addWidget(self.hub_on_btn)
        extras_layout.addWidget(self.hub_off_btn)
        extras_layout.addWidget(self.led_on_btn)
        extras_layout.addWidget(self.led_off_btn)
        extras_layout.addWidget(self.alert_on_btn)
        extras_layout.addWidget(self.alert_off_btn)
        extras_layout.addWidget(self.wp_on_btn)
        extras_layout.addWidget(self.wp_off_btn)
        extras_layout.addWidget(self.fan_on_btn)
        extras_layout.addWidget(self.fan_off_btn)
        extras_group.setLayout(extras_layout)
        layout.addWidget(extras_group)

        # Row 5: Refresh
        hb_refresh = QHBoxLayout()
        hb_refresh.addWidget(self.refresh_btn)
        hb_refresh.addStretch()
        layout.addLayout(hb_refresh)

        # Row 6: Status summary
        layout.addWidget(self.status_label)

        self.control_tab.setLayout(layout)

        # Connect signals
        self.board_combo.currentIndexChanged.connect(self._on_board_changed)
        self.all_on_btn.clicked.connect(self._all_on)
        self.all_off_btn.clicked.connect(self._all_off)
        self.hub_on_btn.clicked.connect(partial(self._run_extra, "hub", "on"))
        self.hub_off_btn.clicked.connect(partial(self._run_extra, "hub", "off"))
        self.led_on_btn.clicked.connect(partial(self._run_extra, "led", "on"))
        self.led_off_btn.clicked.connect(partial(self._run_extra, "led", "off"))
        self.alert_on_btn.clicked.connect(partial(self._run_extra, "alert", "on"))
        self.alert_off_btn.clicked.connect(partial(self._run_extra, "alert", "off"))
        self.wp_on_btn.clicked.connect(partial(self._run_extra, "wp", "on"))
        self.wp_off_btn.clicked.connect(partial(self._run_extra, "wp", "off"))
        self.fan_on_btn.clicked.connect(partial(self._run_extra, "fan", "on"))
        self.fan_off_btn.clicked.connect(partial(self._run_extra, "fan", "off"))
        self.refresh_btn.clicked.connect(self._refresh_status)

    # --------------------------------------------------
    # Build Health Tab UI (unchanged)
    # --------------------------------------------------
    def _build_health_tab(self):
        layout = QVBoxLayout()

        local_group = QGroupBox("Local Controller Pi Stats")
        local_layout = QVBoxLayout()
        local_layout.addWidget(self.local_cpu_lbl)
        local_layout.addWidget(self.local_ram_lbl)
        local_layout.addWidget(self.local_temp_lbl)
        local_layout.addWidget(self.local_net_lbl)
        local_group.setLayout(local_layout)
        layout.addWidget(local_group)

        remote_group = QGroupBox("Remote Node Stats (via SSH)")
        remote_group.setObjectName("RemoteStatsGroup")
        remote_layout = QVBoxLayout()
        remote_group.setLayout(remote_layout)
        layout.addWidget(remote_group)

        hb = QHBoxLayout()
        hb.addWidget(self.refresh_health_btn)
        hb.addStretch()
        layout.addLayout(hb)

        self.health_tab.setLayout(layout)

        self.health_timer = QTimer()
        self.health_timer.setInterval(5000)
        self.health_timer.timeout.connect(self._update_local_stats)
        self.health_timer.start()

        self.refresh_health_btn.clicked.connect(self._refresh_both_local_and_remote)

    # --------------------------------------------------
    # Handle board selection change
    # --------------------------------------------------
    def _on_board_changed(self, index):
        bd_class = self.board_combo.itemData(index)
        if bd_class is None:
            return
        self.current_board_def = bd_class

        # Rebuild per-node buttons
        self._build_node_buttons()

        # Enable/disable extras based on board class
        self.hub_on_btn.setEnabled(bd_class.supports_hub_led)
        self.hub_off_btn.setEnabled(bd_class.supports_hub_led)
        self.led_on_btn.setEnabled(bd_class.supports_hub_led)
        self.led_off_btn.setEnabled(bd_class.supports_hub_led)
        self.alert_on_btn.setEnabled(bd_class.supports_alert)
        self.alert_off_btn.setEnabled(bd_class.supports_alert)
        self.wp_on_btn.setEnabled(bd_class.supports_wp)
        self.wp_off_btn.setEnabled(bd_class.supports_wp)
        # Fan always available
        self.fan_on_btn.setEnabled(True)
        self.fan_off_btn.setEnabled(True)

        # Refresh status and health
        self._refresh_status()
        self._update_local_stats()

    # --------------------------------------------------
    # Create per-node On/Off buttons dynamically
    # --------------------------------------------------
    def _build_node_buttons(self):
        # Clear existing buttons
        for widgets in self.node_buttons.values():
            for w in widgets:
                w.setParent(None)
                w.deleteLater()
        self.node_buttons.clear()

        layout = self.node_group.layout()
        # Clear layout items
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        # For each node, add two buttons
        labels = self.current_board_def.valid_node_labels()
        for idx, node_label in enumerate(labels):
            row = idx // 4  # wrap every 4 per row
            col = (idx % 4) * 2

            btn_on = QPushButton(f"{node_label.upper()} On")
            btn_off = QPushButton(f"{node_label.upper()} Off")
            self.node_buttons[node_label] = (btn_on, btn_off)

            btn_on.clicked.connect(partial(self._node_on, node_label))
            btn_off.clicked.connect(partial(self._node_off, node_label))

            layout.addWidget(btn_on, row, col)
            layout.addWidget(btn_off, row, col + 1)

    # --------------------------------------------------
    # Turn a single node on
    # --------------------------------------------------
    def _node_on(self, node_label):
        args = ["on", node_label]
        rc, out, err = run_clusterctrl_command(args)
        if rc != 0:
            QMessageBox.critical(self, "Error", f"Failed to power ON {node_label.upper()}: {err}")
        else:
            self._refresh_status()

    # --------------------------------------------------
    # Turn a single node off
    # --------------------------------------------------
    def _node_off(self, node_label):
        args = ["off", node_label]
        rc, out, err = run_clusterctrl_command(args)
        if rc != 0:
            QMessageBox.critical(self, "Error", f"Failed to power OFF {node_label.upper()}: {err}")
        else:
            self._refresh_status()

    # --------------------------------------------------
    # Turn all nodes on
    # --------------------------------------------------
    def _all_on(self):
        args = self.current_board_def.command_all_on()
        rc, out, err = run_clusterctrl_command(args)
        if rc != 0:
            QMessageBox.critical(self, "Error", f"Failed to power ON all: {err}")
        else:
            self._refresh_status()

    # --------------------------------------------------
    # Turn all nodes off
    # --------------------------------------------------
    def _all_off(self):
        args = self.current_board_def.command_all_off()
        rc, out, err = run_clusterctrl_command(args)
        if rc != 0:
            QMessageBox.critical(self, "Error", f"Failed to power OFF all: {err}")
        else:
            self._refresh_status()

    # --------------------------------------------------
    # Toggle extras (hub/led/alert/wp/fan)
    # --------------------------------------------------
    def _run_extra(self, extra, state):
        support_map = {
            "hub": self.current_board_def.supports_hub_led,
            "led": self.current_board_def.supports_hub_led,
            "alert": self.current_board_def.supports_alert,
            "wp": self.current_board_def.supports_wp,
            "fan": True
        }
        if not support_map.get(extra, False):
            QMessageBox.warning(self, "Unsupported", f"{self.current_board_def.name} does not support '{extra}' control.")
            return
        args = [extra, state]
        rc, out, err = run_clusterctrl_command(args)
        if rc != 0:
            QMessageBox.critical(self, "Error", f"Failed to run 'clusterctrl {extra} {state}': {err}")
        else:
            self._refresh_status()

    # --------------------------------------------------
    # Refresh control‐tab status
    # --------------------------------------------------
    def _refresh_status(self):
        status, err = parse_clusterctrl_status()
        if err:
            QMessageBox.critical(self, "Error", err)
            return

        node_states = []
        for nl in self.current_board_def.valid_node_labels():
            val = status.get(nl, "0")
            node_states.append(f"{nl.upper()}={'ON' if val=='1' else 'OFF'}")

        extras_states = []
        if self.current_board_def.supports_hub_led:
            hub_val = status.get("hub", "0")
            extras_states.append(f"HUB={'ON' if hub_val=='1' else 'OFF'}")
            led_val = status.get("led", "0")
            extras_states.append(f"LED={'ON' if led_val=='1' else 'OFF'}")
        if self.current_board_def.supports_alert:
            alert_val = status.get("hat_alert", status.get("alert", "0"))
            extras_states.append(f"ALERT={'ON' if alert_val=='1' else 'OFF'}")
        if self.current_board_def.supports_wp:
            wp_val = status.get("wp", "0")
            extras_states.append(f"WP={'ON' if wp_val=='1' else 'OFF'}")
        fan_val = status.get("fan", None)
        if fan_val is not None:
            extras_states.append(f"FAN={'ON' if fan_val=='1' else 'OFF'}")

        summary = " | ".join(node_states + extras_states)
        self.status_label.setText(f"Status: {summary}")

    # --------------------------------------------------
    # Update local stats (CPU, RAM, Temp, Network)
    # --------------------------------------------------
    def _update_local_stats(self):
        cpu_percent = psutil.cpu_percent(interval=0.1)
        self.local_cpu_lbl.setText(f"CPU Usage: {cpu_percent:.1f}%")

        vm = psutil.virtual_memory()
        self.local_ram_lbl.setText(
            f"RAM Usage: {vm.percent:.1f}% ({vm.used//(1024**2)} MiB of {vm.total//(1024**2)} MiB)"
        )

        try:
            proc = subprocess.run(
                ["/usr/bin/vcgencmd", "measure_temp"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
            )
            out = proc.stdout.strip()
            if out.startswith("temp=") and "'" in out:
                temp_val = out.split("=")[1].split("'")[0]
                self.local_temp_lbl.setText(f"Temperature: {temp_val} °C")
            else:
                self.local_temp_lbl.setText("Temperature: N/A")
        except Exception:
            self.local_temp_lbl.setText("Temperature: Error")

        net = psutil.net_io_counters()
        sent_mib = net.bytes_sent / (1024**2)
        recv_mib = net.bytes_recv / (1024**2)
        self.local_net_lbl.setText(f"Network: ↑{sent_mib:.1f} MiB   ↓{recv_mib:.1f} MiB")

    # --------------------------------------------------
    # Update remote stats via SSH
    # --------------------------------------------------
    def _update_remote_stats(self):
        for node_key, lbl in self.remote_stat_labels.items():
            hostname = f"pi@{node_key}.local"
            remote_py = (
                "import psutil;"
                "cpu=psutil.cpu_percent(interval=0.1);"
                "ram=psutil.virtual_memory().percent;"
                "net=psutil.net_io_counters();"
                "print(f'{cpu:.1f},{ram:.1f},{net.bytes_sent//(1024*1024)},{net.bytes_recv//(1024*1024)}')"
            )
            ssh_cmd = (
                f"ssh -o BatchMode=yes -o ConnectTimeout=2 {hostname} "
                f"\"/usr/bin/vcgencmd measure_temp && python3 -c '{remote_py}'\""
            )
            try:
                completed = subprocess.run(
                    shlex.split(ssh_cmd),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=True
                )
                out_lines = [ln.strip() for ln in completed.stdout.splitlines() if ln.strip()]
                temp_line = out_lines[0] if len(out_lines) >= 1 else ""
                cpu_ram_net = out_lines[1] if len(out_lines) >= 2 else ""

                if temp_line.startswith("temp=") and "'" in temp_line:
                    temp_val = temp_line.split("=")[1].split("'")[0]
                else:
                    temp_val = "N/A"

                if "," in cpu_ram_net:
                    cpu_val, ram_val, sent_val, recv_val = cpu_ram_net.split(",")
                else:
                    cpu_val, ram_val, sent_val, recv_val = ("N/A", "N/A", "0", "0")

                lbl.setText(
                    f"{node_key.upper()}: CPU {cpu_val}% | RAM {ram_val}% | "
                    f"Temp {temp_val}°C | Net ↑{sent_val}MiB ↓{recv_val}MiB"
                )
            except Exception:
                lbl.setText(f"{node_key.upper()}: Unreachable / Error")

    # --------------------------------------------------
    # Combined refresh for local + remote stats
    # --------------------------------------------------
    def _refresh_both_local_and_remote(self):
        self._update_local_stats()
        self._update_remote_stats()

    # --------------------------------------------------
    # Perform a `git pull` in the install directory, safely handling local changes
    # --------------------------------------------------
    def _perform_update(self):
        repo_dir = os.path.dirname(os.path.abspath(__file__))

        # Ensure this is a git repo
        if not os.path.isdir(os.path.join(repo_dir, ".git")):
            QMessageBox.warning(
                self, "Update Failed",
                "This folder is not a Git repository.\nCannot pull updates."
            )
            return

        # Check for local changes
        if git_has_local_changes(repo_dir):
            reply = QMessageBox.question(
                self, "Local Changes Detected",
                "You have uncommitted changes in the repository.\n"
                "Updating will discard them.\n"
                "Do you want to proceed and overwrite local changes?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
            # Discard local changes
            try:
                subprocess.run(["git", "reset", "--hard"], cwd=repo_dir, check=True)
            except subprocess.CalledProcessError as e:
                QMessageBox.critical(
                    self, "Reset Failed",
                    f"Failed to discard local changes:\n{e.stderr.strip()}"
                )
                return

        # Now pull
        try:
            proc = subprocess.run(
                ["git", "pull"],
                cwd=repo_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True
            )
            output = proc.stdout.strip()
            QMessageBox.information(
                self, "Update Complete",
                f"Git pull succeeded:\n{output}"
            )
        except subprocess.CalledProcessError as e:
            QMessageBox.critical(
                self, "Update Error",
                f"Git pull failed:\n{e.stderr.strip()}"
            )

# --------------------------------------------------
# Main entrypoint
# --------------------------------------------------

def main():
    app = QApplication(sys.argv)
    window = ClusterCtrlGUI()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
