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
  "$DEPLOY_PATH/REVISION" \
  "$DEPLOY_PATH/analytics-mcp-deploy.tar.gz"

cp -a "$RELEASE_DIR"/. "$DEPLOY_PATH"/
rm -f "$ARCHIVE"

VENV_DIR="$DEPLOY_PATH/.venv"
"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install --force-reinstall "$DEPLOY_PATH"/dist/*.whl
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
echo "Installed virtual environment: $VENV_DIR"
echo "Start command: $DEPLOY_PATH/start.sh"
echo "Release snapshot: $RELEASE_DIR"
