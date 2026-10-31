#!/bin/sh
# Restore /work/backup.file into the database selected by the PG* variables.
set -eu
rc=0
pg_restore --clean --if-exists --no-owner --no-privileges --dbname="$PGDATABASE" /work/backup.file || rc=$?
[ "$rc" -le 1 ] || exit "$rc"
# Exit code 1 means non-fatal errors, typically extensions the app role cannot drop or create.
[ "$rc" -eq 0 ] || echo "WARNING: pg_restore ignored errors; review the output above" >&2
