#!/usr/bin/env bash

#==============================================================================
# install.sh
#
# Installs dependencies for the ClusterCTRL GUI, makes the main script
# executable, and prints a “done” message.
#
# Usage:
#   bash install.sh
#
# After running this, the user can launch:
#   ./clusterctrl_gui.py
#
# For a one-liner installer, see the “README.md” below.
#==============================================================================

set -e

echo "Updating package lists..."
sudo apt update

echo "Installing PyQt5 and psutil..."
sudo apt install -y python3-pyqt5 python3-psutil

# If pip is preferred / psutil wasn’t installed via apt:
# echo "Installing psutil via pip..."
# pip3 install --user psutil

echo "Setting execute permission on clusterctrl_gui.py..."
chmod +x clusterctrl_gui.py

echo
echo "Installation complete!"
echo "You can now run the GUI with:"
echo "  ./clusterctrl_gui.py"
