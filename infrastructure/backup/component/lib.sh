#!/bin/sh
# Shared helpers for the remote-storage backup jobs. Sourced by the other scripts.
set -eu
: "${APP:?APP is required}" "${ITEM:?ITEM is required}"

# rclone may try to rewrite its config (token refresh); the Secret mount is read-only.
export RCLONE_CONFIG=/tmp/rclone.conf
export HOME=/tmp
# Deleted backups must free quota immediately instead of piling up in the Drive trash.
export RCLONE_DRIVE_USE_TRASH=false
cp /storage-config/rclone.conf "$RCLONE_CONFIG"

REMOTE="${STORAGE_REMOTE:-storage}"
DEST="${REMOTE}:backups/${APP}/${ITEM}"
KEEP_LAST="${KEEP_LAST:-7}"

timestamp() { date -u +%Y%m%dT%H%M%SZ; }

# Upload one file, then keep only the newest KEEP_LAST backups (names sort by timestamp).
upload_and_prune() {
  rclone copyto "$1" "$DEST/$(basename "$1")" --retries 5
  echo "uploaded $DEST/$(basename "$1")"
  rclone lsf "$DEST" --files-only | sort -r | tail -n "+$((KEEP_LAST + 1))" |
    while read -r old; do
      echo "retention: deleting $DEST/$old"
      rclone deletefile "$DEST/$old"
    done
}
