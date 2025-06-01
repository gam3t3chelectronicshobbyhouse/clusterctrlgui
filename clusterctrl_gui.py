#!/usr/bin/env python3
"""
clusterctrl_gui.py

A PyQt5 GUI for controlling ClusterHAT/ClusterCTRL boards AND monitoring system
health (CPU/RAM/network/temperature) locally and on each Pi node via SSH.

This version includes:
  - Dropdown for selecting any supported board version (v2.x, v1.x, Single, Triple, A+6).
  - Single toggle button per node with an LED icon above (green/red) indicating on/off.
  - "All On" / "All Off" buttons.
  - Fan On/Off and other extras.
  - "Update from GitHub" only in the File menu.
  - Footer with "Created by Gam3t3ch Electronics 2025" (linking to http://gam3t3ch.com) at bottom-left,
    and a "Donate" button (linking to PayPalMe) at bottom-right.
  - A "Help" tab with usage instructions and troubleshooting.
  - A "Settings" tab to configure SSH credentials, refresh interval, theme, notifications, etc.
  - Improved status summary visually.

Requirements:
  - PyQt5 (`sudo apt install python3-pyqt5`)
  - psutil (`pip3 install psutil`)
  - Passwordless SSH set up to each node (e.g., pi@p1.local, pi@p2.local, …), or configure SSH in Settings.
  - The `vcgencmd` utility available on all Raspberry Pis (standard on Raspberry Pi OS).
  - `clusterctrl` utility installed and in `$PATH` on the controller Pi.
"""

import sys
import subprocess
import shlex
import os
import json
import psutil
from functools import partial
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QMessageBox, QGroupBox, QTabWidget, QAction,
    QMenuBar, QTextEdit, QSpacerItem, QSizePolicy, QLineEdit, QFileDialog,
    QSpinBox, QCheckBox
)
from PyQt5.QtGui import QIcon, QPixmap, QDesktopServices
from PyQt5.QtCore import Qt, QTimer, QUrl

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
        self.setGeometry(100, 100, 900, 600)

        # Path to config file
        self.config_path = os.path.expanduser("~/.config/clusterctrlgui/config.json")
        self.settings = self._load_settings()

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

        # --- Central Widget: tabs + footer ---
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

        # Tabs
        self.tabs = QTabWidget()
        self.control_tab = QWidget()
        self.health_tab = QWidget()
        self.help_tab = QWidget()
        self.settings_tab = QWidget()
        self.tabs.addTab(self.control_tab, "Control")
        self.tabs.addTab(self.health_tab, "System Health")
        self.tabs.addTab(self.help_tab, "Help")
        self.tabs.addTab(self.settings_tab, "Settings")
        main_layout.addWidget(self.tabs)

        # Footer: left label and right donate button
        footer_layout = QHBoxLayout()
        self.footer_label = QLabel(
            '<a href="http://gam3t3ch.com">Created by Gam3t3ch Electronics 2025</a>'
        )
        self.footer_label.setOpenExternalLinks(True)
        footer_layout.addWidget(self.footer_label, alignment=Qt.AlignLeft)
        footer_layout.addItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        self.donate_btn = QPushButton("Donate")
        self.donate_btn.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl("https://www.paypal.com/paypalme/gam3t3ch")
        ))
        footer_layout.addWidget(self.donate_btn, alignment=Qt.AlignRight)

        main_layout.addLayout(footer_layout)

        # --- Load LED icons (resized according to settings) ---
        size = self.settings.get("led_icon_size", 16)
        self.icon_green = QPixmap("icons/icon_green.png").scaled(
            size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.icon_red = QPixmap("icons/icon_red.png").scaled(
            size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )

        # --- Control‐tab widgets ---
        self.board_combo = QComboBox()
        self.node_widgets = {}       # {"p1": (icon_label, toggle_btn), ...}
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
        self.status_label = QLabel()
        self.status_label.setStyleSheet("font-weight: bold; font-size: 14px;")

        # --- Health‐tab widgets ---
        self.local_cpu_lbl = QLabel("CPU Usage: N/A")
        self.local_ram_lbl = QLabel("RAM Usage: N/A")
        self.local_temp_lbl = QLabel("Temperature: N/A °C")
        self.local_net_lbl = QLabel("Network (sent/recv): N/A")
        self.remote_stat_labels = {}
        self.refresh_health_btn = QPushButton("Refresh Health Stats")

        # --- Help‐tab and Settings‐tab to build after ---
        self._build_control_tab()
        self._build_health_tab()
        self._build_help_tab()
        self._build_settings_tab()

        # Populate dropdown with all supported boards
        for bd in ALL_BOARDS:
            self.board_combo.addItem(bd.name, bd)

        # Set initial board selection
        if self.board_combo.count() > 0:
            self.board_combo.setCurrentIndex(0)
            self._on_board_changed(0)

        # Apply theme (if dark)
        if self.settings.get("theme", "light") == "dark":
            self._apply_dark_theme()

    # --------------------------------------------------
    # Load or create default settings
    # --------------------------------------------------
    def _load_settings(self):
        # Ensure config directory exists
        cfg_dir = os.path.dirname(self.config_path)
        os.makedirs(cfg_dir, exist_ok=True)

        # Default structure
        default = {
            "ssh": {},
            "refresh_interval": 5,
            "theme": "light",
            "led_icon_size": 16,
            "play_sound_on_off": False,
            "cpu_alert_threshold": 80,
            "email_alert": ""
        }
        # SSH defaults for each possible node across all boards
        for bd in ALL_BOARDS:
            for node_label in bd.valid_node_labels():
                default["ssh"].setdefault(node_label, {
                    "user_host": f"pi@{node_label}.local",
                    "keyfile": os.path.expanduser("~/.ssh/id_rsa")
                })

        try:
            with open(self.config_path, "r") as f:
                loaded = json.load(f)
            # Merge loaded over default
            for k, v in default.items():
                if k not in loaded:
                    loaded[k] = v
            # Ensure all SSH entries exist
            for node_label, creds in default["ssh"].items():
                if node_label not in loaded["ssh"]:
                    loaded["ssh"][node_label] = creds
            return loaded
        except Exception:
            return default

    # --------------------------------------------------
    # Save settings to disk
    # --------------------------------------------------
    def _save_settings(self):
        try:
            with open(self.config_path, "w") as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save settings:\n{e}")

    # --------------------------------------------------
    # Build Control Tab UI
    # --------------------------------------------------
    def _build_control_tab(self):
        layout = QVBoxLayout()

        # Row 1: Board selection
        hb1 = QHBoxLayout()
        hb1.addWidget(QLabel("Select Board Version:"))
        hb1.addWidget(self.board_combo)
        hb1.addStretch()
        layout.addLayout(hb1)

        # Row 2: Node controls
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

        # Row 4: Extras (hub/LED/alert/WP/fan)
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
        layout.addWidget(self.status_label, alignment=Qt.AlignCenter)

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
    # Build Health Tab UI
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

        # Auto‐refresh local stats at configured interval
        self.health_timer = QTimer()
        self.health_timer.setInterval(self.settings.get("refresh_interval", 5) * 1000)
        self.health_timer.timeout.connect(self._update_local_stats)
        self.health_timer.start()

        self.refresh_health_btn.clicked.connect(self._refresh_both_local_and_remote)

    # --------------------------------------------------
    # Build Help Tab UI
    # --------------------------------------------------
    def _build_help_tab(self):
        layout = QVBoxLayout()
        help_text = """
<h2>How to Use PiCluster Control</h2>
<p><strong>Control Tab:</strong></p>
<ul>
  <li>Select your board version from the dropdown (e.g., ClusterHAT v2.x).</li>
  <li>Each Pi node has a toggle button with a colored LED icon above it:
    <ul>
      <li><span style="color:green;">●</span> Green: ON</li>
      <li><span style="color:red;">●</span> Red: OFF</li>
    </ul>
  </li>
  <li>Click the node button to toggle power on/off.</li>
  <li>Use <em>All On</em> / <em>All Off</em> to power all nodes at once.</li>
  <li>Extras panel:
    <ul>
      <li><em>Hub ON/OFF</em> (if supported)</li>
      <li><em>LED ON/OFF</em> (if supported)</li>
      <li><em>Alert ON/OFF</em> (if supported)</li>
      <li><em>WP ON/OFF</em> (if supported)</li>
      <li><em>Fan ON/OFF</em></li>
    </ul>
  </li>
  <li>Click <em>Refresh Status</em> to update icons and the status summary below.</li>
</ul>

<p><strong>System Health Tab:</strong></p>
<ul>
  <li>Shows CPU, RAM, Temperature, and Network I/O of the controller Pi (auto-refresh every N seconds).</li>
  <li>Shows CPU, RAM, Temp, and Network I/O of each node (via SSH).</li>
  <li>Ensure SSH credentials are correct in <strong>Settings</strong> (username, host, keyfile).</li>
</ul>

<p><strong>Help & Troubleshooting:</strong></p>
<ul>
  <li><strong>Problems Connecting to Nodes:</strong>
    <ul>
      <li>Test SSH under <strong>Settings → SSH Credentials</strong>.</li>
      <li>Use <code>ssh -i &lt;keyfile&gt; &lt;user@host&gt; echo OK</code> from a terminal.</li>
    </ul>
  </li>
  <li><strong>clusterctrl Not Found:</strong>
    <ul>
      <li>Ensure <code>clusterctrl</code> is installed: <code>which clusterctrl</code>.</li>
      <li>Install via: <code>sudo apt install clusterhat-ctrl</code> or use the official image.</li>
    </ul>
  </li>
  <li><strong>GPU Temperature Not Available:</strong>
    <ul>
      <li>Ensure <code>vcgencmd</code> exists: <code>which vcgencmd</code>.</li>
    </ul>
  </li>
  <li><strong>Update Fails:</strong>
    <ul>
      <li>Use <em>File → Update from GitHub</em>. If local changes exist, you will be prompted to overwrite.</li>
    </ul>
  </li>
</ul>
"""
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setHtml(help_text)
        layout.addWidget(text_edit)
        self.help_tab.setLayout(layout)

    # --------------------------------------------------
    # Build Settings Tab UI
    # --------------------------------------------------
    def _build_settings_tab(self):
        layout = QVBoxLayout()

        # SSH Credentials section
        ssh_group = QGroupBox("SSH Credentials")
        ssh_layout = QVBoxLayout()
        ssh_group.setLayout(ssh_layout)
        layout.addWidget(ssh_group)

        self.ssh_fields = {}
        for node_label in sorted(self.settings["ssh"].keys()):
            row = QHBoxLayout()
            user_host_edit = QLineEdit(self.settings["ssh"][node_label]["user_host"])
            keyfile_edit = QLineEdit(self.settings["ssh"][node_label]["keyfile"])
            browse_btn = QPushButton("Browse…")
            test_btn = QPushButton("Test SSH")

            browse_btn.clicked.connect(lambda _, nl=node_label: self._browse_keyfile(nl))
            test_btn.clicked.connect(lambda _, nl=node_label: self._test_ssh(nl))

            row.addWidget(QLabel(node_label.upper() + ":"))
            row.addWidget(user_host_edit)
            row.addWidget(keyfile_edit)
            row.addWidget(browse_btn)
            row.addWidget(test_btn)
            ssh_layout.addLayout(row)

            self.ssh_fields[node_label] = (user_host_edit, keyfile_edit)

        # Refresh interval
        refresh_row = QHBoxLayout()
        self.refresh_spin = QSpinBox()
        self.refresh_spin.setRange(1, 60)
        self.refresh_spin.setValue(self.settings.get("refresh_interval", 5))
        refresh_row.addWidget(QLabel("Auto-Refresh (seconds):"))
        refresh_row.addWidget(self.refresh_spin)
        refresh_row.addStretch()
        layout.addLayout(refresh_row)

        # Theme selection
        theme_row = QHBoxLayout()
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["light", "dark"])
        self.theme_combo.setCurrentText(self.settings.get("theme", "light"))
        theme_row.addWidget(QLabel("Theme:"))
        theme_row.addWidget(self.theme_combo)
        theme_row.addStretch()
        layout.addLayout(theme_row)

        # LED icon size
        icon_row = QHBoxLayout()
        self.icon_spin = QSpinBox()
        self.icon_spin.setRange(8, 32)
        self.icon_spin.setValue(self.settings.get("led_icon_size", 16))
        icon_row.addWidget(QLabel("LED Icon Size (px):"))
        icon_row.addWidget(self.icon_spin)
        icon_row.addStretch()
        layout.addLayout(icon_row)

        # Play sound on node toggle
        sound_row = QHBoxLayout()
        self.sound_checkbox = QCheckBox("Play sound on node ON/OFF")
        self.sound_checkbox.setChecked(self.settings.get("play_sound_on_off", False))
        sound_row.addWidget(self.sound_checkbox)
        sound_row.addStretch()
        layout.addLayout(sound_row)

        # CPU alert threshold
        cpu_row = QHBoxLayout()
        self.cpu_spin = QSpinBox()
        self.cpu_spin.setRange(10, 100)
        self.cpu_spin.setValue(self.settings.get("cpu_alert_threshold", 80))
        cpu_row.addWidget(QLabel("CPU Alert > (%) :"))
        cpu_row.addWidget(self.cpu_spin)
        cpu_row.addStretch()
        layout.addLayout(cpu_row)

        # Email alert
        email_row = QHBoxLayout()
        self.email_edit = QLineEdit(self.settings.get("email_alert", ""))
        self.test_email_btn = QPushButton("Test Email")
        # For simplicity, Test Email is a placeholder—not implemented
        self.test_email_btn.clicked.connect(lambda: QMessageBox.information(
            self, "Test Email", "Email test not implemented."
        ))
        email_row.addWidget(QLabel("Email for alerts:"))
        email_row.addWidget(self.email_edit)
        email_row.addWidget(self.test_email_btn)
        layout.addLayout(email_row)

        # Spacer and Save/Cancel
        layout.addStretch()
        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save")
        cancel_btn = QPushButton("Cancel")
        save_btn.clicked.connect(self._settings_save_clicked)
        cancel_btn.clicked.connect(self._settings_cancel_clicked)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.settings_tab.setLayout(layout)

    # --------------------------------------------------
    # Browse for SSH keyfile
    # --------------------------------------------------
    def _browse_keyfile(self, node_label):
        path, _ = QFileDialog.getOpenFileName(
            self, f"Select Keyfile for {node_label.upper()}",
            os.path.expanduser("~/.ssh")
        )
        if path:
            self.ssh_fields[node_label][1].setText(path)

    # --------------------------------------------------
    # Test SSH connection for a given node
    # --------------------------------------------------
    def _test_ssh(self, node_label):
        user_host = self.ssh_fields[node_label][0].text().strip()
        keyfile = self.ssh_fields[node_label][1].text().strip()
        if not user_host or not keyfile:
            QMessageBox.warning(self, "SSH Test", "Fill in both user@host and keyfile.")
            return
        try:
            proc = subprocess.run(
                ["ssh", "-i", keyfile, "-o", "BatchMode=yes", "-o", "ConnectTimeout=2",
                 user_host, "echo OK"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
            )
            QMessageBox.information(self, "SSH Test", f"Success: {proc.stdout.strip()}")
        except subprocess.CalledProcessError as e:
            QMessageBox.critical(self, "SSH Test Failed", e.stderr.strip())

    # --------------------------------------------------
    # Save settings when “Save” is clicked
    # --------------------------------------------------
    def _settings_save_clicked(self):
        # Update settings dict from UI fields
        for node_label, (uh_edit, key_edit) in self.ssh_fields.items():
            self.settings["ssh"][node_label]["user_host"] = uh_edit.text().strip()
            self.settings["ssh"][node_label]["keyfile"] = key_edit.text().strip()

        self.settings["refresh_interval"] = self.refresh_spin.value()
        self.settings["theme"] = self.theme_combo.currentText()
        self.settings["led_icon_size"] = self.icon_spin.value()
        self.settings["play_sound_on_off"] = self.sound_checkbox.isChecked()
        self.settings["cpu_alert_threshold"] = self.cpu_spin.value()
        self.settings["email_alert"] = self.email_edit.text().strip()

        self._save_settings()
        QMessageBox.information(self, "Settings", "Settings saved successfully. Please restart to apply icon size and theme changes.")

    # --------------------------------------------------
    # Cancel changes and revert UI fields
    # --------------------------------------------------
    def _settings_cancel_clicked(self):
        for node_label, (uh_edit, key_edit) in self.ssh_fields.items():
            uh_edit.setText(self.settings["ssh"][node_label]["user_host"])
            key_edit.setText(self.settings["ssh"][node_label]["keyfile"])

        self.refresh_spin.setValue(self.settings["refresh_interval"])
        self.theme_combo.setCurrentText(self.settings["theme"])
        self.icon_spin.setValue(self.settings["led_icon_size"])
        self.sound_checkbox.setChecked(self.settings["play_sound_on_off"])
        self.cpu_spin.setValue(self.settings["cpu_alert_threshold"])
        self.email_edit.setText(self.settings["email_alert"])

    # --------------------------------------------------
    # Handle board selection change
    # --------------------------------------------------
    def _on_board_changed(self, index):
        bd_class = self.board_combo.itemData(index)
        if bd_class is None:
            return
        self.current_board_def = bd_class

        # Rebuild per-node widgets
        self._build_node_widgets()

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
    # Create per-node LED icon + toggle button
    # --------------------------------------------------
    def _build_node_widgets(self):
        # Clear existing
        for icon_label, toggle_btn in self.node_widgets.values():
            icon_label.setParent(None)
            toggle_btn.setParent(None)
        self.node_widgets.clear()

        layout = self.node_group.layout()
        # Clear layout items
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)

        # For each node, create icon + button
        labels = self.current_board_def.valid_node_labels()
        for idx, node_label in enumerate(labels):
            row = idx // 4  # 4 per row
            col = (idx % 4) * 2

            icon_label = QLabel()
            icon_label.setAlignment(Qt.AlignCenter)
            icon_label.setPixmap(self.icon_red)  # default off

            toggle_btn = QPushButton(node_label.upper())
            toggle_btn.clicked.connect(partial(self._toggle_node, node_label))

            self.node_widgets[node_label] = (icon_label, toggle_btn)

            layout.addWidget(icon_label, row * 2, col, 1, 2, alignment=Qt.AlignCenter)
            layout.addWidget(toggle_btn, row * 2 + 1, col, 1, 2)

    # --------------------------------------------------
    # Toggle a node on/off based on its current state
    # --------------------------------------------------
    def _toggle_node(self, node_label):
        status, err = parse_clusterctrl_status()
        if err:
            QMessageBox.critical(self, "Error", err)
            return

        current = status.get(node_label, "0")
        if current == "1":
            args = ["off", node_label]
        else:
            args = ["on", node_label]

        rc, out, err = run_clusterctrl_command(args)
        if rc != 0:
            QMessageBox.critical(self, "Error", f"Failed to toggle {node_label.upper()}: {err}")
        else:
            self._refresh_status()
            if self.settings.get("play_sound_on_off", False):
                # Sound feedback could be implemented here
                pass

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
            if self.settings.get("play_sound_on_off", False):
                pass

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
            if self.settings.get("play_sound_on_off", False):
                pass

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
    # Refresh control‐tab status, updating icons and summary
    # --------------------------------------------------
    def _refresh_status(self):
        status, err = parse_clusterctrl_status()
        if err:
            QMessageBox.critical(self, "Error", err)
            return

        # Update each node's icon
        for node_label, (icon_label, _) in self.node_widgets.items():
            val = status.get(node_label, "0")
            if val == "1":
                icon_label.setPixmap(self.icon_green)
            else:
                icon_label.setPixmap(self.icon_red)

        # Update summary text
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

        summary = "   |   ".join(node_states + extras_states)
        self.status_label.setText(summary)

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
            creds = self.settings["ssh"].get(node_key, {})
            user_host = creds.get("user_host", f"pi@{node_key}.local")
            keyfile = creds.get("keyfile", os.path.expanduser("~/.ssh/id_rsa"))
            remote_py = (
                "import psutil;"
                "cpu=psutil.cpu_percent(interval=0.1);"
                "ram=psutil.virtual_memory().percent;"
                "net=psutil.net_io_counters();"
                "print(f'{cpu:.1f},{ram:.1f},{net.bytes_sent//(1024*1024)},{net.bytes_recv//(1024*1024)}')"
            )
            ssh_cmd = (
                f"ssh -i {keyfile} -o BatchMode=yes -o ConnectTimeout=2 {user_host} "
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
    # Apply a simple dark theme via stylesheet
    # --------------------------------------------------
    def _apply_dark_theme(self):
        dark_stylesheet = """
        QMainWindow { background-color: #2e2e2e; }
        QWidget { background-color: #2e2e2e; color: #cccccc; }
        QPushButton { background-color: #444444; color: #ffffff; }
        QLineEdit, QComboBox, QTextEdit, QSpinBox { background-color: #3c3c3c; color: #ffffff; }
        QGroupBox { border: 1px solid #555555; margin-top: 8px; }
        QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 3px; }
        QLabel { color: #ffffff; }
        """
        self.setStyleSheet(dark_stylesheet)

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
