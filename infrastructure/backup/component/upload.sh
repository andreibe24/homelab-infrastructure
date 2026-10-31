#!/bin/sh
# Upload every file in /work to Google Drive and apply the retention policy.
. /scripts/lib.sh
found=0
for file in /work/*; do
  [ -f "$file" ] || continue
  found=1
  upload_and_prune "$file"
done
[ "$found" -eq 1 ] || { echo "nothing to upload in /work" >&2; exit 1; }
