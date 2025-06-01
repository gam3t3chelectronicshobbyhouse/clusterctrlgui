#!/usr/bin/env bash
#
# install.sh
# Installs ClusterCTRL GUI & System Health Monitor
# Clones the repository, installs dependencies, sets up a desktop launcher.
#

set -e

# 1. Variables
REPO_URL="https://github.com/gam3t3chelectronicshobbyhouse/clusterctrlgui.git"
INSTALL_DIR="$HOME/clusterctrlgui"
DESKTOP_FILE="/usr/share/applications/clusterctrlgui.desktop"

echo "=== Installing ClusterCTRL GUI ==="

# 2. Ensure git is installed
if ! command -v git >/dev/null 2>&1; then
  echo "Git not found. Installing git..."
  sudo apt update
  sudo apt install -y git
fi

# 3. Clone or update repository
if [ -d "$INSTALL_DIR" ]; then
  echo "Found existing directory at $INSTALL_DIR. Performing git pull..."
  cd "$INSTALL_DIR"
  git pull
else
  echo "Cloning repository to $INSTALL_DIR..."
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

# 4. Install Python dependencies
echo "Installing Python dependencies (PyQt5, psutil)..."
sudo apt update
sudo apt install -y python3-pyqt5 python3-psutil

# 5. Make main script executable
echo "Making clusterctrl_gui.py executable..."
chmod +x "$INSTALL_DIR/clusterctrl_gui.py"

# 6. Create desktop entry
echo "Creating desktop launcher at $DESKTOP_FILE..."
# If a previous desktop file exists, remove it first
if [ -f "$DESKTOP_FILE" ]; then
  sudo rm "$DESKTOP_FILE"
fi

# Use a generic icon (icon_green.png) as application icon
ICON_PATH="$INSTALL_DIR/icons/icon_green.png"

# Create the .desktop file with sudo
sudo bash -c "cat > $DESKTOP_FILE << EOF
[Desktop Entry]
Name=ClusterCTRL GUI
Comment=Control and monitor your Pi cluster
Exec=$INSTALL_DIR/clusterctrl_gui.py
Icon=$ICON_PATH
Terminal=false
Type=Application
Categories=Utility;
EOF"

# 7. Inform user
echo "Installation complete!"
echo "You can launch the GUI from your application menu (search for 'ClusterCTRL GUI')"
echo "Or run directly:"
echo "  $INSTALL_DIR/clusterctrl_gui.py"
