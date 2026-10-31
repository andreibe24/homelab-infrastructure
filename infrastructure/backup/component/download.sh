#!/bin/sh
# Download FILE (default: the newest backup) to /work/backup.file.
. /scripts/lib.sh
FILE="${FILE:-latest}"
if [ "$FILE" = latest ]; then
  FILE="$(rclone lsf "$DEST" --files-only | sort | tail -n 1)"
fi
[ -n "$FILE" ] || { echo "no backups found in $DEST" >&2; exit 1; }
echo "restoring from $DEST/$FILE"
rclone copyto "$DEST/$FILE" /work/backup.file --retries 5
