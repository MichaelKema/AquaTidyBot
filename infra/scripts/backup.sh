#!/bin/bash
set -euo pipefail
umask 077
source_db=/var/lib/aquatidy/data/aquatidy.sqlite3
[ -f "$source_db" ] || exit 0
install -d -m 700 /var/lib/aquatidy/backups
backup_path=/var/lib/aquatidy/backups/aquatidy-$(date -u +%Y%m%dT%H%M%S).sqlite3
# SQLite's backup API creates a consistent snapshot while reminders are running.
sqlite3 "$source_db" ".timeout 10000" ".backup '$backup_path'"
[ "$(sqlite3 "$backup_path" 'PRAGMA integrity_check;')" = ok ]
gzip "$backup_path"
find /var/lib/aquatidy/backups -type f -name 'aquatidy-*.sqlite3.gz' -mtime +7 -delete
