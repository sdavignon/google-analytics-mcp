#!/usr/bin/env bash
set -euo pipefail

DEPLOY_PATH="${1:?Usage: deploy-vps.sh <deploy-path> <revision>}"
REVISION="${2:?Usage: deploy-vps.sh <deploy-path> <revision>}"
DEPLOY_DIR="$DEPLOY_PATH/.deploy"
ARCHIVE="$DEPLOY_DIR/analytics-mcp-deploy.tar.gz"
RELEASES_DIR="$DEPLOY_DIR/releases"
RELEASE_DIR="$RELEASES_DIR/$REVISION"
CURRENT_LINK="$DEPLOY_PATH/current"

if [ ! -f "$ARCHIVE" ]; then
  echo "Deployment archive was not found at $ARCHIVE" >&2
  exit 1
fi

mkdir -p "$RELEASES_DIR"
rm -rf "$RELEASE_DIR"
mkdir -p "$RELEASE_DIR"
tar -xzf "$ARCHIVE" -C "$RELEASE_DIR"
printf '%s\n' "$REVISION" > "$RELEASE_DIR/REVISION"

# If this path is served by Apache, do not expose Python source or package files directly.
cat > "$RELEASE_DIR/.htaccess" <<'HTACCESS'
Require all denied
HTACCESS

ln -sfn "$RELEASE_DIR" "$CURRENT_LINK"
rm -f "$ARCHIVE" "$DEPLOY_PATH/analytics-mcp-deploy.tar.gz"

# Keep the latest five releases to avoid filling the VPS over time.
if command -v find >/dev/null 2>&1; then
  find "$RELEASES_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' \
    | sort -rn \
    | tail -n +6 \
    | cut -d' ' -f2- \
    | while IFS= read -r old_release; do
        rm -rf "$old_release"
      done
fi

echo "Deployed $REVISION to $RELEASE_DIR"
echo "Current release: $CURRENT_LINK"
