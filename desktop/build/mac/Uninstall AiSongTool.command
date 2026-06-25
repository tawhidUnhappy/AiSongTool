#!/bin/sh
# macOS has no built-in uninstaller — this script (bundled into the DMG
# alongside the .app, see electron-builder.yml's mac.target dmg config)
# deletes both the per-user app-data root (models/caches/jobs/output/
# settings — see paths.ts's dataDir(), which resolves to
# ~/Library/Application Support/AiSongTool via Electron's
# app.getPath('appData') on macOS) and the installed .app itself.
set -e

DATA_DIR="$HOME/Library/Application Support/AiSongTool"
APP_PATH="/Applications/AiSongTool.app"

echo "This will permanently delete:"
echo "  $DATA_DIR"
echo "  $APP_PATH"
printf "Continue? [y/N] "
read -r REPLY
case "$REPLY" in
  y|Y) ;;
  *) echo "Cancelled."; exit 0 ;;
esac

rm -rf "$DATA_DIR"
rm -rf "$APP_PATH"
echo "AiSongTool has been uninstalled."
