#!/usr/bin/env bash
#
# install.sh
# Installs ClusterCTRL GUI & System Health Monitor, sets up SSH keys, strips icon profiles,
# and creates a working desktop launcher in ~/.local/share/applications.
#

set -e

# 1. Variables
REPO_URL="https://github.com/gam3t3chelectronicshobbyhouse/clusterctrlgui.git"
INSTALL_DIR="$HOME/clusterctrlgui"
LOCAL_APPS_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$LOCAL_APPS_DIR/clusterctrlgui.desktop"
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
  if ssh-copy-id -i "$SSH_PUB" "$HOST" < /dev/null 2>/dev/null; then
    echo "Success."
  else
    echo "Failed (host may be offline or credentials incorrect)."
  fi
done
echo "=== SSH setup complete ==="
echo

# 7. Strip ICC profiles from icons (to suppress libpng iCCP warnings)
if command -v mogrify >/dev/null 2>&1; then
  echo "Stripping ICC profiles from PNG icons with mogrify..."
  mogrify -strip "$INSTALL_DIR/icons/"*.png
elif command -v pngcrush >/dev/null 2>&1; then
  echo "Stripping ICC profiles from PNG icons with pngcrush..."
  for f in "$INSTALL_DIR/icons/"*.png; do
    pngcrush -ow -rem allb -reduce "$f"
  done
else
  echo "Neither mogrify nor pngcrush installed—skipping icon stripping. You may still see libpng warnings."
fi

# 8. Make main script executable
echo "Making clusterctrl_gui.py executable..."
chmod +x "$INSTALL_DIR/clusterctrl_gui.py"

# 9. Create desktop entry in ~/.local/share/applications
echo "Creating desktop launcher at $DESKTOP_FILE..."
mkdir -p "$LOCAL_APPS_DIR"

cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Name=ClusterCTRL GUI
Comment=Control and monitor your Pi cluster
Exec=python3 $INSTALL_DIR/clusterctrl_gui.py
Icon=$INSTALL_DIR/icons/icon_green.png
Terminal=false
Type=Application
Categories=Utility;
EOF

chmod +x "$DESKTOP_FILE"

# 10. Inform user
echo
echo "Installation complete!"
echo
echo "• If you still see 'libpng warning: iCCP…' messages, ensure mogrify or pngcrush is installed."
echo "• A desktop shortcut should now be available in your application menu as “ClusterCTRL GUI.”"
echo "• If it doesn’t appear immediately, try logging out/in or running:"
echo "      update-desktop-database ~/.local/share/applications"
echo
echo "You can also launch the GUI directly via:"
echo "  python3 $INSTALL_DIR/clusterctrl_gui.py"
