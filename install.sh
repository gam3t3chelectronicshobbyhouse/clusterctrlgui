#!/usr/bin/env bash
#
# install.sh
# Installs ClusterCTRL GUI & System Health Monitor, sets up SSH keys by powering on each Pi Zero node
# (one at a time), waiting up to 120 seconds for SSH, copying the key, then powering it off.
# Ensures the fan is turned on immediately and off at the end.
#

set -e

# 1. Variables
REPO_URL="https://github.com/gam3t3chelectronicshobbyhouse/clusterctrlgui.git"
INSTALL_DIR="$HOME/clusterctrlgui"
LOCAL_APPS_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$LOCAL_APPS_DIR/clusterctrlgui.desktop"
SSH_KEY="$HOME/.ssh/id_rsa"
SSH_PUB="$HOME/.ssh/id_rsa.pub"
NODE_LABELS=( "p1" "p2" "p3" "p4" )  # Valid on this board
SSH_TIMEOUT=5       # seconds per SSH attempt
MAX_WAIT=120        # maximum seconds to wait for each host to become reachable
SLEEP_INTERVAL=5    # seconds between attempts

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

# 6. Turn ON fan immediately
echo
echo "=== Turning ON fan ==="
clusterctrl fan on || echo "Warning: 'clusterctrl fan on' may have failed."

# 7. For each Pi node: power on, wait for SSH, copy key, then power off
echo
echo "=== Distributing SSH keys node by node ==="
for LABEL in "${NODE_LABELS[@]}"; do
  HOST="pi@${LABEL}.local"

  echo
  echo "— Processing $LABEL —"
  echo "Powering ON $LABEL..."
  if clusterctrl on "$LABEL"; then
    echo "Waiting up to $MAX_WAIT seconds for $HOST to become SSH-accessible..."
  else
    echo "Warning: 'clusterctrl on $LABEL' failed. Skipping $LABEL."
    continue
  fi

  elapsed=0
  while [ $elapsed -lt $MAX_WAIT ]; do
    if ssh -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=$SSH_TIMEOUT "$HOST" "echo up" >/dev/null 2>&1; then
      echo "  → $HOST is reachable via SSH."
      break
    else
      echo -n "."
      sleep $SLEEP_INTERVAL
      elapsed=$((elapsed + SLEEP_INTERVAL))
    fi
  done

  if [ $elapsed -ge $MAX_WAIT ]; then
    echo
    echo "  → Timeout ($MAX_WAIT seconds). $HOST did not respond. Leaving $LABEL powered on for manual setup."
    continue
  fi

  echo "Copying SSH key to $HOST..."
  if ssh-copy-id -i "$SSH_PUB" "$HOST" < /dev/null 2>/dev/null; then
    echo "  → SSH key copied successfully to $HOST."
  else
    echo "  → Failed to copy SSH key to $HOST. Please set up manually."
  fi

  echo "Powering OFF $LABEL..."
  if clusterctrl off "$LABEL"; then
    echo "  → $LABEL powered off."
  else
    echo "  → Warning: 'clusterctrl off $LABEL' failed. $LABEL may still be on."
  fi
done

echo
echo "=== SSH key distribution complete ==="
echo "Any node that timed out remains powered on. Configure manually if needed."

# 8. Strip ICC profiles from icons (to suppress libpng warnings)
if command -v mogrify >/dev/null 2>&1; then
  echo "Stripping ICC profiles from PNG icons with mogrify..."
  mogrify -strip "$INSTALL_DIR/icons/"*.png
elif command -v pngcrush >/dev/null 2>&1; then
  echo "Stripping ICC profiles from PNG icons with pngcrush..."
  for f in "$INSTALL_DIR/icons/"*.png; do
    pngcrush -ow -rem allb -reduce "$f"
  done
else
  echo "Neither mogrify nor pngcrush installed—skipping icon stripping."
fi

# 9. Turn OFF fan
echo
echo "=== Turning OFF fan ==="
clusterctrl fan off || echo "Warning: 'clusterctrl fan off' may have failed."

# 10. Make main script executable
echo
echo "Making clusterctrl_gui.py executable..."
chmod +x "$INSTALL_DIR/clusterctrl_gui.py"

# 11. Create desktop entry in ~/.local/share/applications
echo "Creating desktop launcher at $DESKTOP_FILE..."
mkdir -p "$LOCAL_APPS_DIR"

cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Name=ClusterCTRL GUI
Comment=Control and monitor your Pi Zero cluster
Exec=python3 $INSTALL_DIR/clusterctrl_gui.py
Icon=$INSTALL_DIR/icons/icon_green.png
Terminal=false
Type=Application
Categories=Utility;
EOF

chmod +x "$DESKTOP_FILE"

# 12. Inform user
echo
echo "Installation complete!"
echo
echo "• SSH keys were distributed individually to each Pi Zero (p1–p4)."
echo "  If any node did not respond, it remains powered on for manual setup."
echo "• The fan was turned on early and turned off at the end."
echo "• A desktop shortcut is available as “ClusterCTRL GUI.”"
echo "  If it doesn’t appear, run:"
echo "      update-desktop-database ~/.local/share/applications"
echo
echo "To launch the GUI directly, run:"
echo "  python3 $INSTALL_DIR/clusterctrl_gui.py"
