#!/bin/sh
# Replace the contents of DEST_DIR (a mounted PVC) with /work/backup.file.
set -eu
: "${DEST_DIR:?DEST_DIR is required}"
find "$DEST_DIR" -mindepth 1 -delete
tar -C "$DEST_DIR" -xzf /work/backup.file
