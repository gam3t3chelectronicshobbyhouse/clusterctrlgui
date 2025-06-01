#!/usr/bin/env python3
"""
clusterctrl_gui.py

A PyQt5 GUI for controlling ClusterHAT/ClusterCTRL boards AND monitoring system
health (CPU/RAM/network/temperature) locally and on each Pi node via SSH.

This version adds:
  - An “Update” button that runs `git pull` in the install directory,  
    fetching any new files from GitHub and updating changed files.
  - A menu bar with a “File” menu containing:
      • “Update” (same as the Update button)
      • “Exit”
    (You can attach an icon to “Update” by placing a PNG at icons/update.png.)
  - Note: The desktop‐menu launcher (“Launch”) is created via the install script
    as a .desktop file (see install.sh), not inside the GUI itself.
"""

import sys
import subprocess
import shlex
import os
import psutil
from functools import partial
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QCheckBox, QMessageBox, QGroupBox, QTabWidget,
    QAction, QMenuBar
)
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtCore import Qt, QTimer

# --------------------------------------------------
# Utility functions
# --------------------------------------------------

def run_clusterctrl_command(args_list):
    """
    Run a clusterctrl command, return (return_code, stdout, stderr).
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
        return [f"p{i}" for i in range(1, cls.supports_nodes + 1)]

    @classmethod
    def command_power_on(cls, nodes):
        return ["on"] + nodes

    @classmethod
    def command_power_off(cls, nodes):
        return ["off"] + nodes

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


# --------------------------------------------------
# Main Window
# --------------------------------------------------

class ClusterCtrlGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PiCluster Control & Monitoring")
        self.setGeometry(100, 100, 700, 500)

        # Icons for ON/OFF (16×16 PNGs)
        self.icon_on = QIcon("icons/icon_green.png")
        self.icon_off = QIcon("icons/icon_red.png")

        # Current board definition
        self.current_board_def = None

        # --- Menubar & “File” menu ---
        menubar = QMenuBar(self)
        file_menu = menubar.addMenu("File")

        # “Update” action
        update_icon_path = "icons/update.png"  # place a 16×16 PNG here if desired
        if os.path.exists(update_icon_path):
            update_icon = QIcon(update_icon_path)
        else:
            update_icon = QIcon()  # no icon fallback
        update_action = QAction(update_icon, "Update from GitHub", self)
        update_action.triggered.connect(self._perform_update)
        file_menu.addAction(update_action)

        # Separator, then “Exit”
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
        self.power_on_sel_btn = QPushButton("Power ON Selected")
        self.power_off_sel_btn = QPushButton("Power OFF Selected")
        self.node_checkboxes = []
        self.node_group = QGroupBox("Pi Nodes")
        self.hub_on_btn = QPushButton("Hub ON")
        self.hub_off_btn = QPushButton("Hub OFF")
        self.led_on_btn = QPushButton("LED ON")
        self.led_off_btn = QPushButton("LED OFF")
        self.alert_on_btn = QPushButton("Alert ON")
        self.alert_off_btn = QPushButton("Alert OFF")
        self.wp_on_btn = QPushButton("WP ON")
        self.wp_off_btn = QPushButton("WP OFF")
        self.refresh_btn = QPushButton("Refresh Status")
        self.update_btn = QPushButton("Update from GitHub")
        self.status_label = QLabel("Status: Unknown")
        self.node_status_labels = {}

        # --- Health‐tab widgets ---
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

        # Detect boards and populate dropdown
        self._detect_and_populate_boards()

        # If any board detected, select first
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

        # Row 2: Power buttons
        hb2 = QHBoxLayout()
        hb2.addWidget(self.power_on_sel_btn)
        hb2.addWidget(self.power_off_sel_btn)
        layout.addLayout(hb2)

        # Node group placeholder
        node_layout = QHBoxLayout()
        self.node_group.setLayout(node_layout)
        layout.addWidget(self.node_group)

        # Extras group
        extras_layout = QHBoxLayout()
        extras_layout.addWidget(self.hub_on_btn)
        extras_layout.addWidget(self.hub_off_btn)
        extras_layout.addWidget(self.led_on_btn)
        extras_layout.addWidget(self.led_off_btn)
        extras_layout.addWidget(self.alert_on_btn)
        extras_layout.addWidget(self.alert_off_btn)
        extras_layout.addWidget(self.wp_on_btn)
        extras_layout.addWidget(self.wp_off_btn)
        layout.addLayout(extras_layout)

        # Row 3: Refresh + Update buttons
        hb3 = QHBoxLayout()
        hb3.addWidget(self.refresh_btn)
        hb3.addWidget(self.update_btn)
        hb3.addStretch()
        layout.addLayout(hb3)

        # Row 4: Status summary
        layout.addWidget(self.status_label)

        self.control_tab.setLayout(layout)

        # Connect signals
        self.board_combo.currentIndexChanged.connect(self._on_board_changed)
        self.power_on_sel_btn.clicked.connect(self._power_on_selected)
        self.power_off_sel_btn.clicked.connect(self._power_off_selected)
        self.hub_on_btn.clicked.connect(partial(self._run_extra, "hub", "on"))
        self.hub_off_btn.clicked.connect(partial(self._run_extra, "hub", "off"))
        self.led_on_btn.clicked.connect(partial(self._run_extra, "led", "on"))
        self.led_off_btn.clicked.connect(partial(self._run_extra, "led", "off"))
        self.alert_on_btn.clicked.connect(partial(self._run_extra, "alert", "on"))
        self.alert_off_btn.clicked.connect(partial(self._run_extra, "alert", "off"))
        self.wp_on_btn.clicked.connect(partial(self._run_extra, "wp", "on"))
        self.wp_off_btn.clicked.connect(partial(self._run_extra, "wp", "off"))
        self.refresh_btn.clicked.connect(self._refresh_status)
        self.update_btn.clicked.connect(self._perform_update)

    # --------------------------------------------------
    # Build Health Tab UI
    # --------------------------------------------------
    def _build_health_tab(self):
        layout = QVBoxLayout()

        # Local stats group
        local_group = QGroupBox("Local Controller Pi Stats")
        local_layout = QVBoxLayout()
        local_layout.addWidget(self.local_cpu_lbl)
        local_layout.addWidget(self.local_ram_lbl)
        local_layout.addWidget(self.local_temp_lbl)
        local_layout.addWidget(self.local_net_lbl)
        local_group.setLayout(local_layout)
        layout.addWidget(local_group)

        # Remote stats group
        remote_group = QGroupBox("Remote Node Stats (via SSH)")
        remote_group.setObjectName("RemoteStatsGroup")
        remote_layout = QVBoxLayout()
        remote_group.setLayout(remote_layout)
        layout.addWidget(remote_group)

        # Refresh health button
        hb = QHBoxLayout()
        hb.addWidget(self.refresh_health_btn)
        hb.addStretch()
        layout.addLayout(hb)

        self.health_tab.setLayout(layout)

        # Timer to auto-refresh local stats every 5 seconds
        self.health_timer = QTimer()
        self.health_timer.setInterval(5000)  # 5 seconds
        self.health_timer.timeout.connect(self._update_local_stats)
        self.health_timer.start()

        # Manual refresh
        self.refresh_health_btn.clicked.connect(self._refresh_both_local_and_remote)

    # --------------------------------------------------
    # Populate board dropdown
    # --------------------------------------------------
    def _detect_and_populate_boards(self):
        status, err = parse_clusterctrl_status()
        if err:
            QMessageBox.critical(self, "Error", err)
            return

        detected_boards = []
        maxpi = int(status.get("maxpi", "0"))

        if status.get("hat_version_major", "") == "2":
            detected_boards.append(ClusterHATv2)
        elif status.get("hat_version_major", "") == "1":
            detected_boards.append(ClusterHATv1)

        if maxpi == 1:
            detected_boards.append(ClusterCTRLSingle)
        elif maxpi == 3:
            detected_boards.append(ClusterCTRLTriple)
        elif maxpi == 6:
            detected_boards.append(ClusterCTRLA6)

        if not detected_boards:
            detected_boards = [
                ClusterHATv2,
                ClusterHATv1,
                ClusterCTRLSingle,
                ClusterCTRLTriple,
                ClusterCTRLA6
            ]

        for bd in detected_boards:
            self.board_combo.addItem(bd.name, bd)

    # --------------------------------------------------
    # Handle board change
    # --------------------------------------------------
    def _on_board_changed(self, index):
        bd_class = self.board_combo.itemData(index)
        if bd_class is None:
            return
        self.current_board_def = bd_class

        # Clear existing node checkboxes/status
        for cb in self.node_checkboxes:
            cb.setParent(None)
            cb.deleteLater()
        self.node_checkboxes.clear()
        for lbl in self.node_status_labels.values():
            lbl.setParent(None)
            lbl.deleteLater()
        self.node_status_labels.clear()

        # Clear node_group layout
        node_layout = self.node_group.layout()
        for i in reversed(range(node_layout.count())):
            w = node_layout.itemAt(i).widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        # Create new checkboxes & status icons
        for node_label in bd_class.valid_node_labels():
            cb = QCheckBox(node_label.upper())
            self.node_checkboxes.append(cb)
            lbl = QLabel()
            lbl.setPixmap(self.icon_off.pixmap(16, 16))
            lbl.setToolTip(f"{node_label.upper()} status")
            self.node_status_labels[node_label] = lbl

            v = QVBoxLayout()
            v.addWidget(cb, alignment=Qt.AlignCenter)
            v.addWidget(lbl, alignment=Qt.AlignCenter)
            node_layout.addLayout(v)

        # Enable/disable extras
        self.hub_on_btn.setEnabled(bd_class.supports_hub_led)
        self.hub_off_btn.setEnabled(bd_class.supports_hub_led)
        self.led_on_btn.setEnabled(bd_class.supports_hub_led)
        self.led_off_btn.setEnabled(bd_class.supports_hub_led)
        self.alert_on_btn.setEnabled(bd_class.supports_alert)
        self.alert_off_btn.setEnabled(bd_class.supports_alert)
        self.wp_on_btn.setEnabled(bd_class.supports_wp)
        self.wp_off_btn.setEnabled(bd_class.supports_wp)

        # Rebuild remote labels
        self._build_remote_labels()

        # Refresh statuses
        self._refresh_status()
        self._update_local_stats()

    # --------------------------------------------------
    # Recreate remote-stat labels
    # --------------------------------------------------
    def _build_remote_labels(self):
        # Find the remote_group
        remote_group = None
        for widget in self.health_tab.findChildren(QGroupBox):
            if widget.title() == "Remote Node Stats (via SSH)":
                remote_group = widget
                break
        if remote_group is None:
            return

        remote_layout = remote_group.layout()

        # Clear existing labels
        for lbl in self.remote_stat_labels.values():
            lbl.setParent(None)
            lbl.deleteLater()
        self.remote_stat_labels.clear()

        # Create new label per node
        for node_label in self.current_board_def.valid_node_labels():
            lbl = QLabel(f"{node_label.upper()}: N/A")
            lbl.setStyleSheet("font: 12px;")
            remote_layout.addWidget(lbl)
            self.remote_stat_labels[node_label] = lbl

    # --------------------------------------------------
    # Power on selected nodes
    # --------------------------------------------------
    def _power_on_selected(self):
        if not self.current_board_def:
            return
        to_power = [cb.text().lower() for cb in self.node_checkboxes if cb.isChecked()]
        if not to_power:
            QMessageBox.warning(self, "No nodes selected", "Please check at least one node checkbox.")
            return

        args = self.current_board_def.command_power_on(to_power)
        rc, out, err = run_clusterctrl_command(args)
        if rc != 0:
            QMessageBox.critical(self, "Error", f"Failed to power on {to_power}: {err}")
        else:
            self.status_label.setText(f"Powered ON: {', '.join(to_power)}")
            self._refresh_status()

    # --------------------------------------------------
    # Power off selected nodes
    # --------------------------------------------------
    def _power_off_selected(self):
        if not self.current_board_def:
            return
        to_power = [cb.text().lower() for cb in self.node_checkboxes if cb.isChecked()]
        if not to_power:
            QMessageBox.warning(self, "No nodes selected", "Please check at least one node checkbox.")
            return

        args = self.current_board_def.command_power_off(to_power)
        rc, out, err = run_clusterctrl_command(args)
        if rc != 0:
            QMessageBox.critical(self, "Error", f"Failed to power off {to_power}: {err}")
        else:
            self.status_label.setText(f"Powered OFF: {', '.join(to_power)}")
            self._refresh_status()

    # --------------------------------------------------
    # Toggle extras (hub/led/alert/wp)
    # --------------------------------------------------
    def _run_extra(self, extra, state):
        if not self.current_board_def:
            return
        attr_map = {
            "hub": self.current_board_def.supports_hub_led,
            "led": self.current_board_def.supports_hub_led,
            "alert": self.current_board_def.supports_alert,
            "wp": self.current_board_def.supports_wp
        }
        if not attr_map.get(extra, False):
            QMessageBox.warning(self, "Unsupported",
                                 f"{self.current_board_def.name} does not support '{extra}' control.")
            return

        args = [extra, state]
        rc, out, err = run_clusterctrl_command(args)
        if rc != 0:
            QMessageBox.critical(self, "Error", f"Failed to run 'clusterctrl {extra} {state}': {err}")
        else:
            self.status_label.setText(f"Ran: clusterctrl {extra} {state}")
            self._refresh_status()

    # --------------------------------------------------
    # Refresh control‐tab status
    # --------------------------------------------------
    def _refresh_status(self):
        status, err = parse_clusterctrl_status()
        if err:
            QMessageBox.critical(self, "Error", err)
            return

        # Node icons
        for node_label, lbl in self.node_status_labels.items():
            val = status.get(node_label, "0")
            if val == "1":
                lbl.setPixmap(self.icon_on.pixmap(16, 16))
                lbl.setToolTip(f"{node_label.upper()}: ON")
            else:
                lbl.setPixmap(self.icon_off.pixmap(16, 16))
                lbl.setToolTip(f"{node_label.upper()}: OFF")

        # Extras
        if self.current_board_def.supports_hub_led:
            hub_val = status.get("hub", "0")
            self.hub_on_btn.setEnabled(hub_val == "0")
            self.hub_off_btn.setEnabled(hub_val == "1")
            led_val = status.get("led", "0")
            self.led_on_btn.setEnabled(led_val == "0")
            self.led_off_btn.setEnabled(led_val == "1")
        if self.current_board_def.supports_alert:
            alert_val = status.get("hat_alert", status.get("alert", "0"))
            self.alert_on_btn.setEnabled(alert_val == "0")
            self.alert_off_btn.setEnabled(alert_val == "1")
        if self.current_board_def.supports_wp:
            wp_val = status.get("wp", "0")
            self.wp_on_btn.setEnabled(wp_val == "0")
            self.wp_off_btn.setEnabled(wp_val == "1")

        # Summary
        node_states = []
        for nl in self.current_board_def.valid_node_labels():
            st = status.get(nl, "0")
            node_states.append(f"{nl.upper()}={'ON' if st=='1' else 'OFF'}")
        extras_states = []
        if self.current_board_def.supports_hub_led:
            extras_states.append(f"HUB={'ON' if status.get('hub','0')=='1' else 'OFF'}")
            extras_states.append(f"LED={'ON' if status.get('led','0')=='1' else 'OFF'}")
        if self.current_board_def.supports_alert:
            extras_states.append(f"ALERT={'ON' if status.get('hat_alert', status.get('alert','0'))=='1' else 'OFF'}")
        if self.current_board_def.supports_wp:
            extras_states.append(f"WP={'ON' if status.get('wp','0')=='1' else 'OFF'}")

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
            f"RAM Usage: {vm.percent:.1f}% ({vm.used//(1024**2)} MiB used of {vm.total//(1024**2)} MiB)"
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
    # Perform a `git pull` in the install directory
    # --------------------------------------------------
    def _perform_update(self):
        """
        Runs `git pull` in the directory where this script resides.
        On success, shows a message. On failure, shows the error.
        """
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        # Ensure it’s actually a git repo
        if not os.path.isdir(os.path.join(repo_dir, ".git")):
            QMessageBox.warning(
                self, "Update Failed",
                "This folder is not a Git repository.\n"
                "Cannot pull updates."
            )
            return

        # Run git pull
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
