#!/usr/bin/env python3
"""
clusterctrl_gui.py

A PyQt5 GUI for controlling ClusterHAT/ClusterCTRL boards AND monitoring system
health (CPU/RAM/network/temperature) locally and on each Pi node via SSH.

Features:
  - Control Tab: select board version, toggle nodes with LED icons, "All On/All Off",
    extras (Hub, LED, Alert, WP, Fan), and status summary.
  - System Health Tab: local CPU/RAM/Temp/Network + remote node stats via SSH.
  - Help Tab: usage instructions.
  - Settings Tab:
      • Pick CNAT or CBRIDGE mode (affects default host/IP for p1…p4).
      • For each node (p1…p4), specify:
          – Username@Host
          – Keyfile path
          – Password (masked)
          – A “Distribute” button that:
              1. Powers ON that node (clusterctrl on <label>)
              2. Waits up to 120 s for SSH (poll every 5 s)
              3. Uses sshpass + ssh-copy-id to install public key
              4. Powers OFF that node
      • Other settings: refresh interval, theme, LED icon size, sounds, CPU‐alert threshold, email address.
  - At startup, ensures ~/.ssh/ exists (so “Keyfile” fields default to ~/.ssh/id_rsa).
  - “Update from GitHub” under File menu with safe handling of local changes.
  - Strips ICC profiles from icons before packaging (via installer), so Qt/libpng warnings are suppressed.
"""

import sys
import os
import json
import time
import subprocess
import shlex
import psutil
from functools import partial

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QMessageBox, QGroupBox, QTabWidget,
    QAction, QMenuBar, QTextEdit, QSpacerItem, QSizePolicy, QLineEdit,
    QFileDialog, QSpinBox, QCheckBox, QInputDialog
)
from PyQt5.QtGui import QPixmap, QDesktopServices
from PyQt5.QtCore import Qt, QTimer, QUrl

# --------------------------------------------------
# Utility functions
# --------------------------------------------------

def run_clusterctrl_command(args_list):
    """
    Run a `clusterctrl` command (e.g. ["on", "p1"]), returning (return_code, stdout, stderr).
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
    Returns True if `git status --porcelain` is non-empty, indicating local changes.
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
        Returns list of node labels, e.g. ["p1","p2", … up to supports_nodes].
        """
        return [f"p{i}" for i in range(1, cls.supports_nodes + 1)]

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

        # 1. Ensure ~/.ssh/ exists so Settings can safely reference it
        ssh_dir = os.path.expanduser("~/.ssh")
        if not os.path.isdir(ssh_dir):
            os.makedirs(ssh_dir, exist_ok=True)
            os.chmod(ssh_dir, 0o700)

        # Path to config file
        self.config_path = os.path.expanduser("~/.config/clusterctrlgui/config.json")
        self.settings = self._load_settings()

        # Current board definition
        self.current_board_def = None

        # --- Menubar & "File" menu ---
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

        # --- Central Widget (tabs + footer) ---
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

        # Footer: left label + right donate button
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

        # --- Load LED icons (scaled by saved setting) ---
        size = self.settings.get("led_icon_size", 16)
        self.icon_green = QPixmap("icons/icon_green.png").scaled(
            size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.icon_red = QPixmap("icons/icon_red.png").scaled(
            size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )

        # --- Control‐tab widgets ---
        self.board_combo = QComboBox()
        self.node_widgets = {}  # {"p1": (icon_label, toggle_btn), ...}
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

        # Build each tab
        self._build_control_tab()
        self._build_health_tab()
        self._build_help_tab()
        self._build_settings_tab()

        # Populate board dropdown
        for bd in ALL_BOARDS:
            self.board_combo.addItem(bd.name, bd)

        # Select first board by default
        if self.board_combo.count() > 0:
            self.board_combo.setCurrentIndex(0)
            self._on_board_changed(0)

        # Apply dark theme if set
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
            "mode": "cnat",                   # default to CNAT
            "ssh": {},                        # SSH creds per node
            "refresh_interval": 5,
            "theme": "light",
            "led_icon_size": 16,
            "play_sound_on_off": False,
            "cpu_alert_threshold": 80,
            "email_alert": ""
        }
        # For each possible node label, provide defaults
        for bd in ALL_BOARDS:
            for node_label in bd.valid_node_labels():
                default["ssh"].setdefault(node_label, {
                    "user_host": f"pi@{node_label}.local",
                    "keyfile": os.path.expanduser("~/.ssh/id_rsa")
                })

        try:
            with open(self.config_path, "r") as f:
                loaded = json.load(f)
            # Merge top‐level keys
            for k, v in default.items():
                if k not in loaded:
                    loaded[k] = v
            # Ensure all SSH entries exist
            for nl, creds in default["ssh"].items():
                if nl not in loaded["ssh"]:
                    loaded["ssh"][l] = creds
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

        # Auto-refresh local stats
        self.health_timer = QTimer()
        self.health_timer.setInterval(self.settings.get("refresh_interval", 5) * 1000)
        self.health_timer.timeout.connect(self._update_local_stats)
        self.health_timer.start()

        self.refresh_health_btn.clicked.connect(self._refresh_both_local_and_remote)

    # --------------------------------------------------
    # Build Help Tab UI (unchanged)
    # --------------------------------------------------
    def _build_help_tab(self):
        layout = QVBoxLayout()
        help_text = """
<h2>How to Use PiCluster Control</h2>
<p><strong>Control Tab:</strong></p>
<ul>
  <li>Select your board version (e.g., ClusterHAT v2.x).</li>
  <li>Each Pi node has a toggle button with a colored LED icon above:
    <ul>
      <li><span style="color:green;">●</span> Green: ON</li>
      <li><span style="color:red;">●</span> Red: OFF</li>
    </ul>
  </li>
  <li>Click a node to turn it ON/OFF.</li>
  <li>Use <em>All On</em> / <em>All Off</em> to power every node at once.</li>
  <li>Extras panel (Hub/LED/Alert/WP/Fan) if supported.</li>
  <li>Click <em>Refresh Status</em> to update icons and summary below.</li>
</ul>

<p><strong>System Health Tab:</strong></p>
<ul>
  <li>Shows CPU, RAM, Temperature, and Network I/O of the controller Pi (auto-refresh every N sec).</li>
  <li>Shows CPU, RAM, Temperature, and Network I/O of each node (via SSH). Ensure SSH is set up in Settings.</li>
</ul>

<p><strong>Settings Tab:</strong></p>
<ul>
  <li>Select <em>CNAT</em> or <em>CBRIDGE</em> mode (affects default hostnames/IPs for Pi Zeros).</li>
  <li>For each node (<strong>p1</strong>–<strong>p4</strong>), specify:
    <ul>
      <li><strong>Username@Host</strong></li>
      <li><strong>Keyfile</strong> (path to your private key, e.g. ~/.ssh/id_rsa)</li>
      <li><strong>Password</strong> (masked; used for ssh-copy-id)</li>
      <li>A <strong>“Distribute”</strong> button that:
        <ol>
          <li>Powers ON that node (clusterctrl on &lt;label&gt;).</li>
          <li>Waits up to 120 s for SSH to respond.</li>
          <li>Uses sshpass + ssh-copy-id to install your public key.</li>
          <li>Powers OFF that node.</li>
        </ol>
      </li>
    </ul>
  </li>
  <li>Adjust auto-refresh interval, theme (light/dark), LED icon size, sound toggles, CPU-alert threshold, email address.</li>
</ul>
"""
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setHtml(help_text)
        layout.addWidget(text_edit)
        self.help_tab.setLayout(layout)

    # --------------------------------------------------
    # Build Settings Tab UI (updated)
    # --------------------------------------------------
    def _build_settings_tab(self):
        layout = QVBoxLayout()

        # 1. CNAT / CBRIDGE mode
        mode_row = QHBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["cnat", "cbridge"])
        self.mode_combo.setCurrentText(self.settings.get("mode", "cnat"))
        mode_row.addWidget(QLabel("Network Mode:"))
        mode_row.addWidget(self.mode_combo)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        # 2. SSH credentials per node (p1..p4)
        ssh_group = QGroupBox("SSH Credentials (per node)")
        ssh_layout = QGridLayout()
        ssh_group.setLayout(ssh_layout)
        layout.addWidget(ssh_group)

        # Headers
        ssh_layout.addWidget(QLabel("Node"), 0, 0)
        ssh_layout.addWidget(QLabel("User@Host"), 0, 1)
        ssh_layout.addWidget(QLabel("Keyfile"), 0, 2)
        ssh_layout.addWidget(QLabel("Password"), 0, 3)
        ssh_layout.addWidget(QLabel("Action"), 0, 4)

        self.ssh_fields = {}  # { "p1": (user_host_edit, keyfile_edit, password_edit, distribute_btn), ... }

        labels = ["p1", "p2", "p3", "p4"]
        for row_idx, node_label in enumerate(labels, start=1):
            # Node label
            ssh_layout.addWidget(QLabel(node_label.upper()), row_idx, 0)

            # Username@Host
            uh_edit = QLineEdit(self.settings["ssh"][node_label]["user_host"])
            ssh_layout.addWidget(uh_edit, row_idx, 1)

            # Keyfile path + Browse button
            kf_edit = QLineEdit(self.settings["ssh"][node_label]["keyfile"])
            browse_btn = QPushButton("Browse…")
            browse_btn.clicked.connect(lambda _, nl=node_label: self._browse_keyfile(nl))
            kf_layout = QHBoxLayout()
            kf_layout.setContentsMargins(0, 0, 0, 0)
            kf_layout.addWidget(kf_edit)
            kf_layout.addWidget(browse_btn)
            ssh_layout.addLayout(kf_layout, row_idx, 2)

            # Password field (masked)
            pw_edit = QLineEdit()
            pw_edit.setEchoMode(QLineEdit.Password)
            ssh_layout.addWidget(pw_edit, row_idx, 3)

            # Distribute button (for this node only)
            dist_btn = QPushButton("Distribute")
            dist_btn.clicked.connect(partial(self._distribute_ssh_key_for_node, node_label))
            ssh_layout.addWidget(dist_btn, row_idx, 4)

            self.ssh_fields[node_label] = (uh_edit, kf_edit, pw_edit, dist_btn)

        # 3. Other settings below SSH section…

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
        self.test_email_btn.clicked.connect(lambda: QMessageBox.information(self, "Test Email", "Email test not implemented."))
        email_row.addWidget(QLabel("Email for alerts:"))
        email_row.addWidget(self.email_edit)
        email_row.addWidget(self.test_email_btn)
        layout.addLayout(email_row)

        # Spacer and Save/Cancel buttons
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
    # Save settings when “Save” is clicked
    # --------------------------------------------------
    def _settings_save_clicked(self):
        # Mode (cnat/cbridge)
        self.settings["mode"] = self.mode_combo.currentText()

        # SSH fields: only save User@Host and Keyfile (NOT password)
        for node_label, (uh_edit, kf_edit, pw_edit, _) in self.ssh_fields.items():
            self.settings["ssh"][node_label]["user_host"] = uh_edit.text().strip()
            self.settings["ssh"][node_label]["keyfile"] = kf_edit.text().strip()

        # Other settings
        self.settings["refresh_interval"] = self.refresh_spin.value()
        self.settings["theme"] = self.theme_combo.currentText()
        self.settings["led_icon_size"] = self.icon_spin.value()
        self.settings["play_sound_on_off"] = self.sound_checkbox.isChecked()
        self.settings["cpu_alert_threshold"] = self.cpu_spin.value()
        self.settings["email_alert"] = self.email_edit.text().strip()

        self._save_settings()
        QMessageBox.information(self, "Settings", "Settings saved. Restart to apply icon & theme changes.")

    # --------------------------------------------------
    # Cancel changes (revert UI fields)
    # --------------------------------------------------
    def _settings_cancel_clicked(self):
        self.mode_combo.setCurrentText(self.settings.get("mode", "cnat"))
        for node_label, (uh_edit, kf_edit, pw_edit, _) in self.ssh_fields.items():
            uh_edit.setText(self.settings["ssh"][node_label]["user_host"])
            kf_edit.setText(self.settings["ssh"][node_label]["keyfile"])
            pw_edit.clear()

        self.refresh_spin.setValue(self.settings["refresh_interval"])
        self.theme_combo.setCurrentText(self.settings["theme"])
        self.icon_spin.setValue(self.settings["led_icon_size"])
        self.sound_checkbox.setChecked(self.settings["play_sound_on_off"])
        self.cpu_spin.setValue(self.settings["cpu_alert_threshold"])
        self.email_edit.setText(self.settings["email_alert"])

    # --------------------------------------------------
    # Distribute SSH key for a single node (node_label)
    # --------------------------------------------------
    def _distribute_ssh_key_for_node(self, node_label):
        """
        Steps for a single node (e.g. "p1"):
          1. Read User@Host + Keyfile + Password from UI
          2. Power ON that node (clusterctrl on <label>)
          3. Wait up to 120 s, polling SSH until it responds
          4. Run sshpass + ssh-copy-id to copy the public key to host
          5. Power OFF that node (clusterctrl off <label>)
        """
        # Extract fields
        uh_edit, kf_edit, pw_edit, dist_btn = self.ssh_fields[node_label]
        user_host = uh_edit.text().strip()
        keyfile = kf_edit.text().strip()
        password = pw_edit.text()  # may be empty if they intend to use key or passwordless

        if not user_host or not keyfile:
            QMessageBox.warning(self, "Missing Info", f"Please specify User@Host and Keyfile for {node_label.upper()}.")
            return

        # 0. Check for sshpass
        if subprocess.run(["which", "sshpass"], stdout=subprocess.DEVNULL).returncode != 0:
            QMessageBox.warning(self, "sshpass Missing", "sshpass is required to distribute SSH keys. Please install it (`sudo apt install sshpass`) first.")
            return

        # 1. Power ON
        rc_on, _, err_on = run_clusterctrl_command(["on", node_label])
        if rc_on != 0:
            QMessageBox.critical(self, "Error", f"Failed to power ON {node_label.upper()}: {err_on}")
            return

        # 2. Wait up to 120 seconds for SSH
        max_wait = 120
        interval = 5
        elapsed = 0
        msg = QMessageBox(self)
        msg.setWindowTitle("Distribute SSH Key")
        msg.setText(f"Waiting for {user_host} to respond (up to {max_wait} s)…")
        msg.setStandardButtons(QMessageBox.NoButton)
        msg.show()

        while elapsed < max_wait:
            try:
                ssh_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout={interval} -i {keyfile} {user_host} echo up"
                completed = subprocess.run(shlex.split(ssh_cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if completed.returncode == 0 and "up" in completed.stdout:
                    break
            except Exception:
                pass
            time.sleep(interval)
            elapsed += interval

        msg.close()

        if elapsed >= max_wait:
            QMessageBox.warning(
                self, "Timeout",
                f"{user_host} did not respond within {max_wait} seconds.\n"
                f"{node_label.upper()} remains powered ON for manual setup."
            )
            return

        # 3. Copy public key using sshpass + ssh-copy-id
        copy_cmd = f"sshpass -p {password} ssh-copy-id -o StrictHostKeyChecking=no -i {keyfile} {user_host}"
        proc = subprocess.run(shlex.split(copy_cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0:
            QMessageBox.critical(
                self, "SSH Copy Failed",
                f"Failed to copy SSH key to {user_host}:\n{proc.stderr.strip()}"
            )
            # Leave node powered on for manual fix
            return

        # 4. Power OFF
        rc_off, _, err_off = run_clusterctrl_command(["off", node_label])
        if rc_off != 0:
            QMessageBox.warning(
                self, "Power Off Failed",
                f"{node_label.upper()} was ON and key copied, but failed to power OFF: {err_off}"
            )
        else:
            QMessageBox.information(self, "Success", f"SSH key copied to {user_host} and {node_label.upper()} powered OFF.")

        # Clear just the password field
        pw_edit.clear()

    # --------------------------------------------------
    # Handle board selection change
    # --------------------------------------------------
    def _on_board_changed(self, index):
        bd_class = self.board_combo.itemData(index)
        if bd_class is None:
            return
        self.current_board_def = bd_class

        # Rebuild node widgets
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
        for icon_label, toggle_btn in self.node_widgets.values():
            icon_label.setParent(None)
            toggle_btn.setParent(None)
        self.node_widgets.clear()

        layout = self.node_group.layout()
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)

        labels = self.current_board_def.valid_node_labels()
        for idx, node_label in enumerate(labels):
            row = idx // 4
            col = (idx % 4) * 2

            icon_label = QLabel()
            icon_label.setAlignment(Qt.AlignCenter)
            icon_label.setPixmap(self.icon_red)

            toggle_btn = QPushButton(node_label.upper())
            toggle_btn.clicked.connect(partial(self._toggle_node, node_label.lower()))

            self.node_widgets[node_label.lower()] = (icon_label, toggle_btn)

            layout.addWidget(icon_label, row * 2, col, 1, 2, alignment=Qt.AlignCenter)
            layout.addWidget(toggle_btn, row * 2 + 1, col, 1, 2)

    # --------------------------------------------------
    # Toggle a node on/off
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
                # Placeholder for sound feedback
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

        # Build summary
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
    # Perform a `git pull` with safe local-changes handling
    # --------------------------------------------------
    def _perform_update(self):
        repo_dir = os.path.dirname(os.path.abspath(__file__))

        if not os.path.isdir(os.path.join(repo_dir, ".git")):
            QMessageBox.warning(self, "Update Failed", "Not a Git repository. Cannot pull updates.")
            return

        if git_has_local_changes(repo_dir):
            reply = QMessageBox.question(
                self, "Local Changes Detected",
                "You have local changes. Pulling will discard them. Proceed?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
            try:
                subprocess.run(["git", "reset", "--hard"], cwd=repo_dir, check=True)
            except subprocess.CalledProcessError as e:
                QMessageBox.critical(self, "Reset Failed", f"Failed to discard changes:\n{e.stderr.strip()}")
                return

        try:
            proc = subprocess.run(
                ["git", "pull"],
                cwd=repo_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True
            )
            QMessageBox.information(self, "Update Complete", f"Git pull succeeded:\n{proc.stdout.strip()}")
        except subprocess.CalledProcessError as e:
            QMessageBox.critical(self, "Update Error", f"Git pull failed:\n{e.stderr.strip()}")

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
