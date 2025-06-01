#!/usr/bin/env bash
#
# install.sh
# Installs ClusterCTRL GUI & System Health Monitor.
# It will:
#   • Create ~/.ssh/ (700) and generate an SSH keypair if missing
#   • Clone (or pull) the repository
#   • Install Python dependencies
#   • Strip ICC profiles from PNG icons (to suppress `libpng` warnings)
#   • Make the main GUI script executable
#   • Create a desktop launcher in ~/.local/share/applications
#

set -e

### ─── 1. VARIABLES ──────────────────────────────────────────────────────────

REPO_URL="https://github.com/gam3t3chelectronicshobbyhouse/clusterctrlgui.git"
INSTALL_DIR="$HOME/clusterctrlgui"
LOCAL_APPS_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$LOCAL_APPS_DIR/clusterctrlgui.desktop"
SSH_DIR="$HOME/.ssh"
SSH_KEY="$SSH_DIR/id_rsa"
SSH_PUB="$SSH_DIR/id_rsa.pub"

### ─── 2. PREPARE ~/.ssh ───────────────────────────────────────────────────────

echo
echo "=== Preparing SSH directory ==="

if [ ! -d "$SSH_DIR" ]; then
  echo "Creating $SSH_DIR …"
  mkdir -p "$SSH_DIR"
  chmod 700 "$SSH_DIR"
else
  echo "$SSH_DIR already exists; ensuring permissions are 700"
  chmod 700 "$SSH_DIR"
fi

# Generate a new SSH keypair if missing
if [ ! -f "$SSH_KEY" ]; then
  echo "Generating new SSH keypair at $SSH_KEY …"
  ssh-keygen -t rsa -b 4096 -f "$SSH_KEY" -N "" -q
  echo "→ Created: $SSH_KEY and $SSH_PUB"
else
  echo "SSH keypair already exists at $SSH_KEY; skipping generation"
fi

### ─── 3. CLONE OR UPDATE REPO ─────────────────────────────────────────────────

echo
echo "=== Installing ClusterCTRL GUI ==="
echo

# Ensure Git is installed
if ! command -v git &>/dev/null; then
  echo "Git not found. Installing git…"
  sudo apt update
  sudo apt install -y git
fi

# Clone or pull the repository
if [ -d "$INSTALL_DIR" ]; then
  echo "Found existing directory at $INSTALL_DIR. Running 'git pull'…"
  cd "$INSTALL_DIR"
  git pull
else
  echo "Cloning repository into $INSTALL_DIR…"
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

### ─── 4. INSTALL PYTHON DEPENDENCIES ───────────────────────────────────────────

echo "Installing Python dependencies (PyQt5, psutil)…"
sudo apt update
sudo apt install -y python3-pyqt5 python3-psutil

### ─── 5. STRIP ICC PROFILES FROM ICONS ────────────────────────────────────────

echo "Stripping ICC profiles from PNG icons to suppress libpng warnings…"
if command -v mogrify &>/dev/null; then
  mogrify -strip "$INSTALL_DIR/icons/"*.png
  echo "→ Stripped icons with mogrify"
elif command -v pngcrush &>/dev/null; then
  for f in "$INSTALL_DIR/icons/"*.png; do
    pngcrush -ow -rem allb -reduce "$f" &>/dev/null
  done
  echo "→ Stripped icons with pngcrush"
else
  echo "!! Neither mogrify nor pngcrush installed—skipping icon stripping"
fi

### ─── 6. MAKE MAIN SCRIPT EXECUTABLE ───────────────────────────────────────────

echo "Making clusterctrl_gui.py executable…"
chmod +x "$INSTALL_DIR/clusterctrl_gui.py"

### ─── 7. CREATE DESKTOP LAUNCHER ──────────────────────────────────────────────

echo "Creating desktop launcher at $DESKTOP_FILE…"
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

### ─── 8. FINISH ───────────────────────────────────────────────────────────────

echo
echo "Installation complete!"
echo
echo "• ~/.ssh/ has been created and an SSH keypair (id_rsa/id_rsa.pub) generated."
echo "• A desktop shortcut (‘ClusterCTRL GUI’) should now appear in your menu."
echo "  If it doesn’t show immediately, run:"
echo "      update-desktop-database ~/.local/share/applications"
echo
echo "• To launch the GUI from a terminal, run:"
echo "      python3 $INSTALL_DIR/clusterctrl_gui.py"
echo

exit 0
