#!/usr/bin/env bash
# create-ubuntu-launchers.sh
# Sets up clickable desktop icons for FC Production on Ubuntu.
# Safe to re-run — overwrites existing files.

set -euo pipefail

BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
START_SCRIPT="$BIN_DIR/start-fc-production"
STOP_SCRIPT="$BIN_DIR/stop-fc-production"
START_DESKTOP="$DESKTOP_DIR/Start FC Production.desktop"
STOP_DESKTOP="$DESKTOP_DIR/Stop FC Production.desktop"

echo ""
echo "=== FC Production — Ubuntu Launcher Setup ==="
echo ""

mkdir -p "$BIN_DIR" "$APPS_DIR"
[[ -d "$DESKTOP_DIR" ]] || mkdir -p "$DESKTOP_DIR"

# ── Write start script ────────────────────────────────────────────────────────
cat > "$START_SCRIPT" << 'STARTSCRIPT'
#!/usr/bin/env bash
# start-fc-production — Start Fresh Collective dev servers and open app in browser

set -euo pipefail

FC_ROOT="$HOME/fc-production"
BACKEND_DIR="$FC_ROOT/backend"
FRONTEND_DIR="$FC_ROOT/frontend"
BROWSER_PROFILE="/tmp/fc-production-browser-profile"
BROWSER_PID_FILE="/tmp/fc-production-browser.pid"
FRONTEND_URL="http://localhost:3000"
WAIT_TIMEOUT=90

if [[ ! -d "$FC_ROOT" ]]; then
  zenity --error --title="FC Production" --text="Project root not found:\n$FC_ROOT" 2>/dev/null \
    || echo "ERROR: $FC_ROOT does not exist." >&2
  exit 1
fi

for dir in "$BACKEND_DIR" "$FRONTEND_DIR"; do
  if [[ ! -d "$dir" ]]; then
    zenity --error --title="FC Production" --text="Directory not found:\n$dir" 2>/dev/null \
      || echo "ERROR: $dir does not exist." >&2
    exit 1
  fi
done

for port in 3000 8000; do
  pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    echo "Clearing port $port (PIDs: $pids)..."
    kill -TERM $pids 2>/dev/null || true
    sleep 1
    remaining=$(lsof -ti tcp:"$port" 2>/dev/null || true)
    [[ -n "$remaining" ]] && kill -KILL $remaining 2>/dev/null || true
  fi
done

BACKEND_CMD="cd '$BACKEND_DIR'"
if [[ -d "$BACKEND_DIR/.venv" ]]; then
  BACKEND_CMD+=" && source .venv/bin/activate"
elif [[ -d "$BACKEND_DIR/venv" ]]; then
  BACKEND_CMD+=" && source venv/bin/activate"
fi
BACKEND_CMD+=" && echo '' && echo '  FC Backend  |  http://127.0.0.1:8000' && echo ''"
BACKEND_CMD+=" && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
BACKEND_CMD+="; echo ''; echo 'Backend exited. Press Enter to close.'; read"

if [[ -f "$FRONTEND_DIR/yarn.lock" ]]; then
  DEV_CMD="yarn dev"
else
  DEV_CMD="npm run dev"
fi

FRONTEND_CMD="cd '$FRONTEND_DIR'"
FRONTEND_CMD+=" && echo '' && echo '  FC Frontend  |  http://localhost:3000' && echo ''"
FRONTEND_CMD+=" && $DEV_CMD"
FRONTEND_CMD+="; echo ''; echo 'Frontend exited. Press Enter to close.'; read"

echo "Launching FC Production servers..."
gnome-terminal \
  --tab --title="FC Backend"  -- bash -c "$BACKEND_CMD" \
  --tab --title="FC Frontend" -- bash -c "$FRONTEND_CMD"

echo "Waiting for frontend at $FRONTEND_URL..."
ELAPSED=0
INTERVAL=2
until curl -sf --max-time 2 "$FRONTEND_URL" > /dev/null 2>&1; do
  if [[ $ELAPSED -ge $WAIT_TIMEOUT ]]; then
    echo "Timed out after ${WAIT_TIMEOUT}s waiting for frontend. Browser not opened."
    exit 0
  fi
  printf "."
  sleep $INTERVAL
  ELAPSED=$((ELAPSED + INTERVAL))
done
echo ""
echo "Frontend is ready."

BROWSER=""
for candidate in google-chrome chromium-browser chromium; do
  if command -v "$candidate" &>/dev/null; then
    BROWSER="$candidate"
    break
  fi
done

if [[ -n "$BROWSER" ]]; then
  echo "Opening app in $BROWSER (app mode, isolated profile)..."
  "$BROWSER" \
    --app="$FRONTEND_URL" \
    --user-data-dir="$BROWSER_PROFILE" \
    --no-first-run \
    --no-default-browser-check \
    --disable-default-apps \
    &>/dev/null &
  echo $! > "$BROWSER_PID_FILE"
  echo "Browser PID $! saved to $BROWSER_PID_FILE"
else
  echo "Chrome/Chromium not found — opening via xdg-open (Stop will not close the window)."
  xdg-open "$FRONTEND_URL" &>/dev/null &
  rm -f "$BROWSER_PID_FILE"
fi

echo ""
echo "=== FC Production is running ==="
echo "  Frontend: $FRONTEND_URL"
echo "  Backend:  http://127.0.0.1:8000"
echo ""
STARTSCRIPT

chmod +x "$START_SCRIPT"
echo "  [OK] Start script: $START_SCRIPT"

# ── Write stop script ─────────────────────────────────────────────────────────
cat > "$STOP_SCRIPT" << 'STOPSCRIPT'
#!/usr/bin/env bash
# stop-fc-production — Stop Fresh Collective dev servers and browser safely

set -uo pipefail

BROWSER_PID_FILE="/tmp/fc-production-browser.pid"
BROWSER_PROFILE="/tmp/fc-production-browser-profile"
STOPPED_ANYTHING=false

stop_port() {
  local port="$1"
  local pids
  pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    echo "Stopping processes on port $port (PIDs: $pids)..."
    kill -TERM $pids 2>/dev/null || true
    sleep 1
    local remaining
    remaining=$(lsof -ti tcp:"$port" 2>/dev/null || true)
    if [[ -n "$remaining" ]]; then
      echo "  Force-killing port $port (PIDs: $remaining)..."
      kill -KILL $remaining 2>/dev/null || true
    fi
    echo "  Port $port cleared."
    STOPPED_ANYTHING=true
  else
    echo "Port $port: nothing running."
  fi
}

stop_by_pattern() {
  local label="$1"
  local pattern="$2"
  local pids
  pids=$(pgrep -f "$pattern" 2>/dev/null | grep -v "^$$\$" || true)
  if [[ -n "$pids" ]]; then
    echo "Stopping $label (PIDs: $pids)..."
    kill -TERM $pids 2>/dev/null || true
    STOPPED_ANYTHING=true
  fi
}

echo ""
echo "=== Stopping FC Production ==="
echo ""

if [[ -f "$BROWSER_PID_FILE" ]]; then
  BROWSER_PID=$(cat "$BROWSER_PID_FILE" 2>/dev/null || true)
  if [[ -n "$BROWSER_PID" ]] && kill -0 "$BROWSER_PID" 2>/dev/null; then
    echo "Closing FC browser window (PID: $BROWSER_PID)..."
    kill -TERM "$BROWSER_PID" 2>/dev/null || true
    sleep 1
    if kill -0 "$BROWSER_PID" 2>/dev/null; then
      kill -KILL "$BROWSER_PID" 2>/dev/null || true
    fi
    echo "  Browser window closed."
    STOPPED_ANYTHING=true
  else
    echo "FC browser window: not running (stale PID file)."
  fi
  rm -f "$BROWSER_PID_FILE"
else
  echo "FC browser window: no PID file found."
fi

remaining_browser=$(pgrep -f "fc-production-browser-profile" 2>/dev/null || true)
if [[ -n "$remaining_browser" ]]; then
  echo "Cleaning up remaining browser processes on FC profile..."
  kill -TERM $remaining_browser 2>/dev/null || true
  STOPPED_ANYTHING=true
fi

echo ""

stop_port 8000
stop_port 3000

echo ""

stop_by_pattern "uvicorn"     "uvicorn app.main:app"
stop_by_pattern "next dev"    "next dev"
stop_by_pattern "npm run dev" "npm run dev"
stop_by_pattern "yarn dev"    "yarn dev"

echo ""
if [[ "$STOPPED_ANYTHING" == "true" ]]; then
  echo "=== FC Production stopped. ==="
else
  echo "=== Nothing was running. ==="
fi
echo ""
STOPSCRIPT

chmod +x "$STOP_SCRIPT"
echo "  [OK] Stop script:  $STOP_SCRIPT"

# ── Write desktop launcher for Start ─────────────────────────────────────────
write_start_desktop() {
  local path="$1"
  cat > "$path" << DESKTOPFILE
[Desktop Entry]
Version=1.0
Type=Application
Name=Start FC Production
Comment=Start Fresh Collective dev servers and open app in browser
Exec=$START_SCRIPT
Icon=utilities-terminal
Terminal=false
Categories=Development;
StartupNotify=false
DESKTOPFILE
  chmod +x "$path"
}

# ── Write desktop launcher for Stop ──────────────────────────────────────────
write_stop_desktop() {
  local path="$1"
  cat > "$path" << DESKTOPFILE
[Desktop Entry]
Version=1.0
Type=Application
Name=Stop FC Production
Comment=Stop Fresh Collective dev servers and close browser window
Exec=gnome-terminal -- bash -c "$STOP_SCRIPT; echo 'Press Enter to close.'; read"
Icon=process-stop
Terminal=false
Categories=Development;
StartupNotify=false
DESKTOPFILE
  chmod +x "$path"
}

write_start_desktop "$APPS_DIR/start-fc-production.desktop"
write_stop_desktop  "$APPS_DIR/stop-fc-production.desktop"
echo "  [OK] App launcher entries: $APPS_DIR"

write_start_desktop "$START_DESKTOP"
write_stop_desktop  "$STOP_DESKTOP"
echo "  [OK] Desktop icons: $DESKTOP_DIR"

if command -v gio &>/dev/null; then
  gio set "$START_DESKTOP" metadata::trusted true 2>/dev/null && \
    echo "  [OK] Trusted: Start FC Production.desktop" || \
    echo "  [--] gio trust not supported on this desktop session (ignore)"
  gio set "$STOP_DESKTOP"  metadata::trusted true 2>/dev/null && \
    echo "  [OK] Trusted: Stop FC Production.desktop"  || \
    echo "  [--] gio trust not supported on this desktop session (ignore)"
else
  echo "  [--] gio not found — you may need to right-click icons and choose Allow Launching"
fi

if command -v update-desktop-database &>/dev/null; then
  update-desktop-database "$APPS_DIR" 2>/dev/null || true
fi

echo ""
echo "=== Setup complete. ==="
echo ""
echo "  Desktop icons: $DESKTOP_DIR"
echo "  App launcher:  $APPS_DIR"
echo "  Start script:  $START_SCRIPT"
echo "  Stop script:   $STOP_SCRIPT"
echo ""
echo "  Browser will open in Chrome/Chromium app mode with an isolated profile."
echo "  Stopping will close only that FC window — your normal browser is safe."
echo ""
echo "  If icons show a question mark, right-click each and choose 'Allow Launching'."
echo ""
