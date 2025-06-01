#!/usr/bin/env bash
#
# install.sh
# Installs ClusterCTRL GUI & System Health Monitor,
# then sets up SSH keys on each Pi Zero (p1–p4) by:
#   • power-on one node at a time
#   • prompting for custom or default IP/hostname
#   • waiting up to 120 seconds for SSH
#   • copying your ~/.ssh/id_rsa.pub via sshpass (prompting for user/password)
#   • powering that node off
# Ensures fan is ON throughout, then OFF at the end.
#
# Finally, it strips ICC profiles from PNG icons (to avoid libpng warnings)
# and places a desktop shortcut in ~/.local/share/applications.

set -e

### ─── 1. VARIABLES ──────────────────────────────────────────────────────────

REPO_URL="https://github.com/gam3t3chelectronicshobbyhouse/clusterctrlgui.git"
INSTALL_DIR="$HOME/clusterctrlgui"
LOCAL_APPS_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$LOCAL_APPS_DIR/clusterctrlgui.desktop"
SSH_KEY="$HOME/.ssh/id_rsa"
SSH_PUB="$HOME/.ssh/id_rsa.pub"
SSH_DIR="$(dirname "$SSH_KEY")"
NODE_LABELS=( "p1" "p2" "p3" "p4" )  # Valid nodes for this board
SSH_TIMEOUT=5       # seconds SSH attempts timeout
MAX_WAIT=60        # max seconds to wait for each node to become reachable
SLEEP_INTERVAL=5    # seconds between SSH checks

### ─── 2. PREAMBLE / CHECKS ────────────────────────────────────────────────────

echo
echo "=== ClusterCTRL GUI Installer & SSH-Key Setup ==="
echo

# 2A. Ask whether CNAT or CBRIDGE is in use on the controller
read -p "Are you running CNAT or CBRIDGE on the controller? (type 'cnat' or 'cbridge'): " MODE
MODE="${MODE,,}"  # lowercase
if [[ "$MODE" != "cnat" && "$MODE" != "cbridge" ]]; then
  echo "Invalid selection. Please run again and choose either 'cnat' or 'cbridge'."
  exit 1
fi
echo "→ Selected mode: $MODE"
echo

# 2B. Ensure git is installed
if ! command -v git &>/dev/null; then
  echo "Git not found. Installing git..."
  sudo apt update
  sudo apt install -y git
fi

# 2C. Clone or pull our GUI repository
if [ -d "$INSTALL_DIR" ]; then
  echo "Found existing directory at $INSTALL_DIR. Doing 'git pull'..."
  cd "$INSTALL_DIR"
  git pull
else
  echo "Cloning GUI repo into $INSTALL_DIR..."
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

# 2D. Install Python dependencies (PyQt5 & psutil)
echo "Installing Python dependencies..."
sudo apt update
sudo apt install -y python3-pyqt5 python3-psutil

# 2E. Install sshpass (to allow non-interactive ssh-copy-id with a password)
if ! command -v sshpass &>/dev/null; then
  echo "Installing sshpass (for automated SSH password login)..."
  sudo apt update
  sudo apt install -y sshpass
else
  echo "sshpass detected—skipping installation."
fi

# 2F. Generate a new SSH keypair if missing
if [ ! -f "$SSH_KEY" ]; then
  echo
  echo "SSH key not found at $SSH_KEY. Generating a new keypair..."
  mkdir -p "$SSH_DIR"
  chmod 700 "$SSH_DIR"
  ssh-keygen -t rsa -b 4096 -f "$SSH_KEY" -N "" -q
  echo "→ Generated: $SSH_KEY and $SSH_PUB"
else
  echo
  echo "SSH keypair already exists at $SSH_KEY. Using that."
fi

### ─── 3. POWER ON FAN ─────────────────────────────────────────────────────────

echo
echo "=== Turning ON the fan ==="
if clusterctrl fan on; then
  echo "→ Fan is ON"
else
  echo "!! Warning: 'clusterctrl fan on' failed. Check your ClusterCTRL board."
fi

### ─── 4. NODE-BY-NODE SSH-KEY DISTRIBUTION ────────────────────────────────────

echo
echo "=== Distribute SSH key to each Pi Zero (p1–p4), one at a time ==="
echo

for LABEL in "${NODE_LABELS[@]}"; do
  echo "──── Processing $LABEL ────"

  # 4A. Power on this node
  echo "1) Powering ON $LABEL..."
  if clusterctrl on "$LABEL"; then
    echo "   → $LABEL powered ON"
  else
    echo "   !! Failed to power on $LABEL. Skipping this node."
    echo "────────────────────────────────────────"
    continue
  fi

  # 4B. Determine default host based on mode
  if [[ "$MODE" == "cnat" ]]; then
    IDX="${LABEL:1}"        # “p1” → “1”
    DEFAULT_HOST="pi@172.19.181.$IDX"
  else
    DEFAULT_HOST="pi@${LABEL}.local"
  fi

  # 4C. Prompt for custom or default host
  read -p "Enter SSH host for $LABEL (default: $DEFAULT_HOST): " CUSTOM
  HOST="${CUSTOM:-$DEFAULT_HOST}"

  echo "   → Using host: $HOST"

  # 4D. Wait for SSH to become reachable
  echo "2) Waiting up to $MAX_WAIT seconds for SSH on $HOST..."
  elapsed=0
  while (( elapsed < MAX_WAIT )); do
    if ssh -o BatchMode=yes -o ConnectTimeout=$SSH_TIMEOUT -i "$SSH_KEY" "$HOST" "echo up" &>/dev/null; then
      echo "   → SSH reachable on $HOST"
      break
    else
      echo -n "."
      sleep "$SLEEP_INTERVAL"
      (( elapsed += SLEEP_INTERVAL ))
    fi
  done

  if (( elapsed >= MAX_WAIT )); then
    echo
    echo "   !! Timeout: SSH did not respond on $HOST within $MAX_WAIT seconds."
    echo "   !! Leaving $LABEL powered ON for manual setup."
    echo "────────────────────────────────────────"
    continue
  fi

  # 4E. Prompt for username (default “pi”) and password
  read -p "Enter SSH username for $HOST (default: 'pi'): " NODE_USER
  NODE_USER="${NODE_USER:-pi}"
  read -sp "Enter SSH password for $NODE_USER@$HOST: " NODE_PASS
  echo

  # 4F. Copy SSH public key via sshpass
  echo "3) Copying SSH key to $NODE_USER@$HOST ..."
  if sshpass -p "$NODE_PASS" ssh-copy-id -o StrictHostKeyChecking=no -i "$SSH_PUB" "$NODE_USER@$HOST" &>/dev/null; then
    echo "   → Public key copied successfully."
  else
    echo "   !! Failed to copy public key to $NODE_USER@$HOST. Check credentials or host."
    echo "   !! Leaving $LABEL powered ON for manual fix."
    echo "────────────────────────────────────────"
    continue
  fi

  # 4G. Power off this node
  echo "4) Powering OFF $LABEL..."
  if clusterctrl off "$LABEL"; then
    echo "   → $LABEL powered OFF"
  else
    echo "   !! Failed to power off $LABEL. It may still be ON."
  fi

  echo "────────────────────────────────────────"
  echo
done

echo
echo "=== SSH key distribution complete ==="
echo "Any node that timed out or failed remains powered ON for manual configuration."
echo

### ─── 5. STRIP ICC PROFILES FROM ICONS (OPTIONAL) ──────────────────────────────

echo "=== Stripping ICC profiles from PNG icons (to suppress libpng warnings) ==="
if command -v mogrify &>/dev/null; then
  mogrify -strip "$INSTALL_DIR/icons/"*.png
  echo "→ Stripped icons via mogrify."
elif command -v pngcrush &>/dev/null; then
  for f in "$INSTALL_DIR/icons/"*.png; do
    pngcrush -ow -rem allb -reduce "$f" &>/dev/null
  done
  echo "→ Stripped icons via pngcrush."
else
  echo "!! Neither mogrify nor pngcrush found—skipping icon stripping."
fi

### ─── 6. TURN OFF FAN ──────────────────────────────────────────────────────────

echo
echo "=== Turning OFF the fan ==="
if clusterctrl fan off; then
  echo "→ Fan is OFF"
else
  echo "!! Failed to turn off fan. You may need to do so manually."
fi

### ─── 7. MAKE GUI SCRIPT EXECUTABLE ───────────────────────────────────────────

echo
echo "Making the GUI script executable..."
chmod +x "$INSTALL_DIR/clusterctrl_gui.py"

### ─── 8. CREATE DESKTOP LAUNCHER ──────────────────────────────────────────────

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

### ─── 9. FINAL MESSAGE ────────────────────────────────────────────────────────

echo
echo "Installation & SSH-Key-Setup is complete!"
echo
echo "• Each Pi Zero (p1–p4) was powered on, SSH credentials and custom IP/hostname prompted,"
echo "  SSH key copied, then powered off. Nodes that timed out remain powered on for manual setup."
echo "• Fan was turned on at start and off at the end."
echo "• A desktop shortcut is available as “ClusterCTRL GUI.”"
echo "  If it doesn’t appear, run:"
echo "      update-desktop-database ~/.local/share/applications"
echo
echo "To launch the GUI directly, run:"
echo "  python3 $INSTALL_DIR/clusterctrl_gui.py"
echo

exit 0
