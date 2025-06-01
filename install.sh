#!/usr/bin/env bash
#
# install.sh
# Installs ClusterCTRL GUI & System Health Monitor,
# then sets up SSH keys on each Pi Zero (p1–p4) by:
#   • power-on one node at a time
#   • waiting up to 120 sec for SSH
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
MAX_WAIT=120        # max seconds to wait for each node to become reachable
SLEEP_INTERVAL=5    # seconds between SSH checks

### ─── 2. PREAMBLE / CHECKS ────────────────────────────────────────────────────

echo
echo "=== ClusterCTRL GUI Installer & SSH‐Key Setup ==="
echo

# 2A. Ask whether CNAT or CBRIDGE is in use on the controller
read -p "Are you running CNAT or CBRIDGE on the controller? (type 'cnat' or 'cbridge'): " MODE
MODE="${MODE,,}"  # lowercase
if [[ "$MODE" != "cnat" && "$MODE" != "cbridge" ]]; then
  echo "Invalid selection. Please edit the script and choose either 'cnat' or 'cbridge'."
  exit 1
fi
echo "→ Selected: $MODE"
echo

# 2B. Ensure git is installed
if ! command -v git &>/dev/null; then
  echo "Git not found. Installing git..."
  sudo apt update
  sudo apt install -y git
fi

# 2C. Clone or pull our GUI repository
if [ -d "$INSTALL_DIR" ]; then
  echo "Found existing $INSTALL_DIR. Doing 'git pull'..."
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

# 2E. Install sshpass (to allow non‐interactive ssh-copy-id with a password)
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

### ─── 4. NODE‐BY‐NODE SSH‐KEY DISTRIBUTION ────────────────────────────────────

echo
echo "=== Distribute SSH key to each Pi Zero (p1–p4), one at a time ==="
echo

# For CNAT mode, the Pi Zero IPs will be 172.19.181.1..4
# For CBRIDGE mode, we’ll assume they are reachable via mDNS as p<1..4>.local
for LABEL in "${NODE_LABELS[@]}"; do
  echo "──── Processing $LABEL ────"

  # 4A. Decide the SSH host address based on selected mode
  if [[ "$MODE" == "cnat" ]]; then
    # CNAT: Pi Zero P1 → 172.19.181.1, P2 → 172.19.181.2, etc.
    IDX="${LABEL:1}"        # “p1” → “1”, “p2” → “2”
    HOST="pi@172.19.181.$IDX"
  else
    # CBRIDGE: Pi Zero P1 → pi@p1.local, P2 → pi@p2.local, etc.
    HOST="pi@${LABEL}.local"
  fi

  echo "1) Powering ON $LABEL..."
  if clusterctrl on "$LABEL"; then
    echo "   → $LABEL powered ON"
  else
    echo "   !! Failed to power on $LABEL. Skipping this node."
    continue
  fi

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
    echo "   !! Timeout: $HOST did not respond in $MAX_WAIT seconds."
    echo "   !! Leaving $LABEL powered ON for manual setup later."
    echo "────────────────────────────────────────"
    continue
  fi

  # 4B. Prompt for username/password for this node
  #     (even though we default to 'pi', they may have changed it)
  read -p "Enter SSH username for $LABEL (default: 'pi'): " NODE_USER
  NODE_USER="${NODE_USER:-pi}"

  # Suppress echo for password
  read -sp "Enter SSH password for $NODE_USER@$HOST: " NODE_PASS
  echo

  # 4C. Copy our public key to that node, using sshpass
  echo "3) Copying SSH public key to $NODE_USER@$HOST ..."
  if sshpass -p "$NODE_PASS" ssh-copy-id -o StrictHostKeyChecking=no -i "$SSH_PUB" "$NODE_USER@$HOST" &>/dev/null; then
    echo "   → Public key copied successfully."
  else
    echo "   !! Failed to copy public key. Credentials may be wrong or host unreachable."
    echo "   !! Leaving $LABEL powered ON for manual fix."
    echo "────────────────────────────────────────"
    continue
  fi

  # 4D. Power OFF this node now that setup is done
  echo "4) Powering OFF $LABEL ..."
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
echo "Any node that timed out or failed will remain powered on for manual configuration."
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
echo "Installation & SSH‐Key‐Setup is complete!"
echo
echo "• If any node did not respond within $MAX_WAIT seconds, it remains powered ON for manual setup."
echo "• You can now launch the GUI via your desktop menu → “ClusterCTRL GUI”."
echo "  If it doesn’t appear immediately, you can run:"
echo "      update-desktop-database ~/.local/share/applications"
echo "• Or run the GUI directly from terminal:"
echo "      python3 $INSTALL_DIR/clusterctrl_gui.py"
echo

exit 0
