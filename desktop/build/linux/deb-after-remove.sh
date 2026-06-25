#!/bin/sh
# electron-builder deb `afterRemove` maintainer script — runs on `apt remove`
# AND `apt purge` alike (dpkg doesn't distinguish for a plain postrm hook the
# way it does for conffiles), deleting every per-user app-data directory this
# app ever wrote (models, caches, jobs, output, settings — see paths.ts's
# dataDir(), which resolves to `~/.config/AiSongTool` on Linux via Electron's
# app.getPath('appData')). Without this, the NSIS/Windows installer's
# deleteAppDataOnUninstall:true has no Linux deb equivalent and the app would
# leave gigabytes of models behind after removal.
set -e

for home_dir in /home/*/ /root/; do
  data_dir="${home_dir}.config/AiSongTool"
  if [ -d "$data_dir" ]; then
    rm -rf "$data_dir"
  fi
done

exit 0
