#!/bin/sh
# Logical dump of one database. Connection settings come from the PG* variables.
set -eu
: "${ITEM:?ITEM is required}"
file="/work/${ITEM}-$(date -u +%Y%m%dT%H%M%SZ).dump"
pg_dump --format=custom --no-owner --no-privileges --file="$file"
# Fail the job if the archive is unreadable instead of uploading a broken backup.
pg_restore --list "$file" >/dev/null
ls -l "$file"
