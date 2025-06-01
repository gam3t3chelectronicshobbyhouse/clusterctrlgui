#!/usr/bin/env bash
#
# uninstall.sh
# Uninstalls ClusterCTRL GUI & System Health Monitor
# Removes installation directory and desktop launcher.
#

set -e

# 1. Variables
INSTALL_DIR="$HOME/clusterctrlgui"
DESKTOP_FILE="/usr/share/applications/clusterctrlgui.desktop"

echo "=== Uninstalling ClusterCTRL GUI ==="

# 2. Remove desktop entry
if [ -f "$DESKTOP_FILE" ]; then
  echo "Removing desktop launcher at $DESKTOP_FILE..."
  sudo rm "$DESKTOP_FILE"
else
  echo "Desktop launcher not found at $DESKTOP_FILE"
fi

# 3. Remove installation directory
if [ -d "$INSTALL_DIR" ]; then
  echo "Removing installation directory at $INSTALL_DIR..."
  rm -rf "$INSTALL_DIR"
else
  echo "Installation directory not found at $INSTALL_DIR"
fi

# 4. Inform user
echo "Uninstallation complete."
