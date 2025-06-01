#!/usr/bin/env bash
#
# install.sh
# Installs ClusterCTRL GUI & System Health Monitor, and sets up SSH keys for Pi nodes.
#

set -e

# 1. Variables
REPO_URL="https://github.com/gam3t3chelectronicshobbyhouse/clusterctrlgui.git"
INSTALL_DIR="$HOME/clusterctrlgui"
DESKTOP_FILE="/usr/share/applications/clusterctrlgui.desktop"
SSH_KEY="$HOME/.ssh/id_rsa"
SSH_PUB="$HOME/.ssh/id_rsa.pub"
NODE_HOSTS=( "pi@p1.local" "pi@p2.local" "pi@p3.local" "pi@p4.local" "pi@p5.local" "pi@p6.local" )

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

# 5. Generate SSH keypair if missing
if [ ! -f "$SSH_KEY" ]; then
  echo "SSH key not found. Generating a new keypair at $SSH_KEY..."
  mkdir -p "$(dirname "$SSH_KEY")"
  chmod 700 "$(dirname "$SSH_KEY")"
  ssh-keygen -t rsa -b 4096 -f "$SSH_KEY" -N ""
  echo "SSH key generated."
else
  echo "SSH key already exists at $SSH_KEY. Skipping generation."
fi

# 6. Distribute public key to each Pi node
echo
echo "=== Distributing SSH public key to Pi nodes ==="
for HOST in "${NODE_HOSTS[@]}"; do
  echo -n "Attempting to copy key to $HOST... "
  # Try ssh-copy-id; ignore errors if host is unreachable
  if ssh-copy-id -i "$SSH_PUB" "$HOST" < /dev/null 2>/dev/null; then
    echo "Success."
  else
    echo "Failed (host may be offline or credentials incorrect)."
  fi
done
echo "=== SSH setup complete ==="
echo

# 7. Make main script executable
echo "Making clusterctrl_gui.py executable..."
chmod +x "$INSTALL_DIR/clusterctrl_gui.py"

# 8. Create desktop entry
echo "Creating desktop launcher at $DESKTOP_FILE..."
if [ -f "$DESKTOP_FILE" ]; then
  sudo rm "$DESKTOP_FILE"
fi

ICON_PATH="$INSTALL_DIR/icons/icon_green.png"
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

# 9. Inform user
echo
echo "Installation complete!"
echo "SSH keys have been generated (if not present) and distributed to p1.local … p6.local."
echo "If any node was unreachable, you can still set up SSH manually or adjust in Settings."
echo
echo "You can launch the GUI from your application menu (search for 'ClusterCTRL GUI')"
echo "Or run directly:"
echo "  $INSTALL_DIR/clusterctrl_gui.py"
