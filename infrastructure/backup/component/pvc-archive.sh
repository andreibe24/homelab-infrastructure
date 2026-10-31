#!/bin/sh
# Archive the directory SRC (a mounted PVC) to /work and upload it.
. /scripts/lib.sh
: "${SRC:?SRC is required}"
file="/work/${ITEM}-$(timestamp).tar.gz"
tar -C "$SRC" -czf "$file" .
tar -tzf "$file" >/dev/null
upload_and_prune "$file"
