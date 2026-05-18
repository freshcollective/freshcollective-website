#!/usr/bin/env bash

set -e

DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
APP_DIR="$HOME/fc-production"
BIN_DIR="$HOME/.local/bin"
APP_LAUNCHER_DIR="$HOME/.local/share/applications"

START_SCRIPT="$BIN_DIR/start-fc-production"
STOP_SCRIPT="$BIN_DIR/stop-fc-production"

mkdir -p "$DESKTOP_DIR"
mkdir -p "$BIN_DIR"
mkdir -p "$APP_LAUNCHER_DIR"

echo "Using desktop folder: $DESKTOP_DIR"

# Make sure scripts exist
if [ ! -f "$START_SCRIPT" ]; then
  echo "ERROR: Start script does not exist:"
  echo "$START_SCRIPT"
  exit 1
fi

if [ ! -f "$STOP_SCRIPT" ]; then
  echo "ERROR: Stop script does not exist:"
  echo "$STOP_SCRIPT"
  exit 1
fi

chmod +x "$START_SCRIPT"
chmod +x "$STOP_SCRIPT"

# Create Start desktop icon
cat > "$DESKTOP_DIR/Start FC Production.desktop" <<EOF2
[Desktop Entry]
Version=1.0
Type=Application
Name=Start FC Production
Comment=Start FC Production frontend and backend
Exec=$START_SCRIPT
Icon=utilities-terminal
Terminal=false
StartupNotify=true
Categories=Development;
EOF2

# Create Stop desktop icon
cat > "$DESKTOP_DIR/Stop FC Production.desktop" <<EOF2
[Desktop Entry]
Version=1.0
Type=Application
Name=Stop FC Production
Comment=Stop FC Production frontend and backend
Exec=$STOP_SCRIPT
Icon=process-stop
Terminal=true
StartupNotify=true
Categories=Development;
EOF2

chmod +x "$DESKTOP_DIR/Start FC Production.desktop"
chmod +x "$DESKTOP_DIR/Stop FC Production.desktop"

# Mark trusted if gio supports it
gio set "$DESKTOP_DIR/Start FC Production.desktop" metadata::trusted true 2>/dev/null || true
gio set "$DESKTOP_DIR/Stop FC Production.desktop" metadata::trusted true 2>/dev/null || true

# Copy to app launcher too
cp "$DESKTOP_DIR/Start FC Production.desktop" "$APP_LAUNCHER_DIR/start-fc-production.desktop"
cp "$DESKTOP_DIR/Stop FC Production.desktop" "$APP_LAUNCHER_DIR/stop-fc-production.desktop"

chmod +x "$APP_LAUNCHER_DIR/start-fc-production.desktop"
chmod +x "$APP_LAUNCHER_DIR/stop-fc-production.desktop"

update-desktop-database "$APP_LAUNCHER_DIR" 2>/dev/null || true

echo ""
echo "Done."
echo ""
echo "Created these desktop files:"
ls -l "$DESKTOP_DIR" | grep "FC Production" || true

echo ""
echo "Now open the Desktop folder:"
echo "nautilus \"$DESKTOP_DIR\""
echo ""
echo "If the icons still look like plain text files, right-click each one and choose:"
echo "Allow Launching"
