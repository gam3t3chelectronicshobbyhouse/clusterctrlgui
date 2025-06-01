#!/usr/bin/env bash
#
# install.sh
# Installs ClusterCTRL GUI & System Health Monitor, sets up SSH keys,
# powers on all Pi Zero nodes, distributes SSH keys, then powers off each node individually.
#

set -e

# 1. Variables
REPO_URL="https://github.com/gam3t3chelectronicshobbyhouse/clusterctrlgui.git"
INSTALL_DIR="$HOME/clusterctrlgui"
LOCAL_APPS_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$LOCAL_APPS_DIR/clusterctrlgui.desktop"
SSH_KEY="$HOME/.ssh/id_rsa"
SSH_PUB="$HOME/.ssh/id_rsa.pub"
# Node labels correspond to Pi Zero ports: p1 through p6 (or fewer if your board has fewer)
NODE_LABELS=( "p1" "p2" "p3" "p4" "p5" "p6" )
SSH_TIMEOUT=5       # seconds per SSH attempt
MAX_WAIT=120        # maximum seconds to wait for each host to come online
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

# 6. Power ON all Pi Zero nodes
echo
echo "=== Powering ON all Pi Zero nodes ==="
clusterctrl on all || echo "Warning: 'clusterctrl on all' may have failed. Check your ClusterCTRL board."
echo "Waiting for nodes to boot (up to $MAX_WAIT seconds each)..."
echo

# 7. Wait for each node to become reachable, distribute SSH key, then power off individually
for LABEL in "${NODE_LABELS[@]}"; do
  HOST="pi@${LABEL}.local"
  echo -n "Waiting for $HOST to be SSH-accessible ... "
  elapsed=0
  while [ $elapsed -lt $MAX_WAIT ]; do
    if ssh -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=$SSH_TIMEOUT "$HOST" "echo up" >/dev/null 2>&1; then
      echo "reachable"
      break
    else
      echo -n "."
      sleep $SLEEP_INTERVAL
      elapsed=$((elapsed + SLEEP_INTERVAL))
    fi
  done

  if [ $elapsed -ge $MAX_WAIT ]; then
    echo
    echo "  → $HOST did not respond within $MAX_WAIT seconds. Skipping key copy and leaving it powered on."
    continue
  fi

  # 7a. Copy SSH public key
  echo -n "Copying SSH key to $HOST ... "
  if ssh-copy-id -i "$SSH_PUB" "$HOST" < /dev/null 2>/dev/null; then
    echo "success"
  else
    echo "failed (credentials or host issue)."
    echo "  → Leaves $LABEL powered on for manual setup."
    continue
  fi

  # 7b. Power off this node now that key is copied
  echo -n "Powering OFF $LABEL ... "
  if clusterctrl off "$LABEL"; then
    echo "done"
  else
    echo "failed (you may need to power off manually)."
  fi
done

echo
echo "=== SSH key distribution complete ==="
echo "Any node that failed to be reached remains powered on. Please configure manually if needed."
echo

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

# 9. Make main script executable
echo "Making clusterctrl_gui.py executable..."
chmod +x "$INSTALL_DIR/clusterctrl_gui.py"

# 10. Create desktop entry in ~/.local/share/applications
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

# 11. Inform user
echo
echo "Installation complete!"
echo
echo "• Each Pi Zero node was powered on, SSH key copied if reachable, then powered off individually."
echo "  If any node was unreachable, it remains powered on for manual troubleshooting."
echo "• A desktop shortcut is available as “ClusterCTRL GUI.”"
echo "  If it doesn’t appear, try logging out/in or running:"
echo "      update-desktop-database ~/.local/share/applications"
echo
echo "To launch the GUI directly, run:"
echo "  python3 $INSTALL_DIR/clusterctrl_gui.py"
