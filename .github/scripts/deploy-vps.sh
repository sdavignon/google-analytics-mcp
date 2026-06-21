#!/usr/bin/env bash
set -euo pipefail

DEPLOY_PATH="${1:?Usage: deploy-vps.sh <deploy-path> <revision>}"
REVISION="${2:?Usage: deploy-vps.sh <deploy-path> <revision> [python-bin]}"
PYTHON_BIN="${3:-python3}"
DEPLOY_DIR="$DEPLOY_PATH/.deploy"
ARCHIVE="$DEPLOY_DIR/analytics-mcp-deploy.tar.gz"
RELEASES_DIR="$DEPLOY_DIR/releases"
RELEASE_DIR="$RELEASES_DIR/$REVISION"

if [ ! -f "$ARCHIVE" ]; then
  echo "Deployment archive was not found at $ARCHIVE" >&2
  exit 1
fi

mkdir -p "$RELEASES_DIR"
rm -rf "$RELEASE_DIR"
mkdir -p "$RELEASE_DIR"
tar -xzf "$ARCHIVE" -C "$RELEASE_DIR"
printf '%s\n' "$REVISION" > "$RELEASE_DIR/REVISION"

# DreamHost points the site at VPS_DEPLOY_PATH, so the active application files
# must live directly in that directory. Keep only deployment internals under
# .deploy, and replace the app-managed files at the web root on each release.
rm -rf \
  "$DEPLOY_PATH/analytics_mcp" \
  "$DEPLOY_PATH/dist" \
  "$DEPLOY_PATH/current" \
  "$DEPLOY_PATH/pyproject.toml" \
  "$DEPLOY_PATH/README.md" \
  "$DEPLOY_PATH/LICENSE" \
  "$DEPLOY_PATH/requirements.txt" \
  "$DEPLOY_PATH/server.py" \
  "$DEPLOY_PATH/passenger_wsgi.py" \
  "$DEPLOY_PATH/start.sh" \
  "$DEPLOY_PATH/index.html" \
  "$DEPLOY_PATH/health.json" \
  "$DEPLOY_PATH/.htaccess" \
  "$DEPLOY_PATH/REVISION" \
  "$DEPLOY_PATH/analytics-mcp-deploy.tar.gz"

cp -a "$RELEASE_DIR"/. "$DEPLOY_PATH"/
rm -f "$ARCHIVE"

WHEEL_PATH=$(find "$DEPLOY_PATH/dist" -maxdepth 1 -type f -name '*.whl' | head -n 1)
if [ -z "$WHEEL_PATH" ]; then
  echo "No wheel file was found in $DEPLOY_PATH/dist" >&2
  exit 1
fi

VENV_DIR="$DEPLOY_PATH/.venv"
START_COMMAND="$VENV_DIR/bin/analytics-mcp-http"
PYTHON_COMMAND="$VENV_DIR/bin/python"
INSTALL_MODE="virtualenv"
rm -rf "$VENV_DIR"
if "$PYTHON_BIN" -m venv "$VENV_DIR"; then
  "$VENV_DIR/bin/python" -m pip install --upgrade pip
  "$VENV_DIR/bin/python" -m pip install --force-reinstall "$WHEEL_PATH"
else
  echo "Could not create a virtualenv with $PYTHON_BIN; falling back to a user-level pip install." >&2
  "$PYTHON_BIN" -m pip install --user --upgrade --force-reinstall "$WHEEL_PATH"
  USER_BASE=$("$PYTHON_BIN" -m site --user-base)
  START_COMMAND="$USER_BASE/bin/analytics-mcp-http"
  PYTHON_COMMAND="$PYTHON_BIN"
  INSTALL_MODE="user"
fi

cat > "$DEPLOY_PATH/start.sh" <<EOF_START
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "\$0")"
if [ -f ./.env ]; then
  set -a
  . ./.env
  set +a
fi
if [ -f ./.secrets/google-application-credentials.json ]; then
  export GOOGLE_APPLICATION_CREDENTIALS="$(pwd)/.secrets/google-application-credentials.json"
fi
exec "$START_COMMAND" --host "${MCP_HTTP_HOST:-127.0.0.1}" --port "${PORT:-${MCP_HTTP_PORT:-8000}}" "\$@"
EOF_START
chmod +x "$DEPLOY_PATH/start.sh"

if [ "${AUTO_START_MCP_HTTP:-1}" = "1" ]; then
  if [ -f "$DEPLOY_DIR/app.pid" ] && kill -0 "$(cat "$DEPLOY_DIR/app.pid")" 2>/dev/null; then
    kill "$(cat "$DEPLOY_DIR/app.pid")"
  fi
  nohup "$DEPLOY_PATH/start.sh" > "$DEPLOY_DIR/app.log" 2>&1 &
  echo $! > "$DEPLOY_DIR/app.pid"
fi

cat > "$DEPLOY_DIR/last-deploy.env" <<EOF_ENV
REVISION=$(printf %q "$REVISION")
INSTALL_MODE=$(printf %q "$INSTALL_MODE")
PYTHON_COMMAND=$(printf %q "$PYTHON_COMMAND")
START_COMMAND=$(printf %q "$START_COMMAND")
EOF_ENV

mkdir -p "$DEPLOY_PATH/tmp"
touch "$DEPLOY_PATH/tmp/restart.txt"

# Keep the latest five release snapshots for troubleshooting without filling the VPS.
if command -v find >/dev/null 2>&1; then
  find "$RELEASES_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' \
    | sort -rn \
    | tail -n +6 \
    | cut -d' ' -f2- \
    | while IFS= read -r old_release; do
        rm -rf "$old_release"
      done
fi

echo "Deployed $REVISION to $DEPLOY_PATH"
echo "Install mode: $INSTALL_MODE"
echo "Start command: $DEPLOY_PATH/start.sh"
echo "Resolved Python command: $PYTHON_COMMAND"
echo "Resolved app command: $START_COMMAND"
echo "Release snapshot: $RELEASE_DIR"
