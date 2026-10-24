#!/bin/sh
set -eu
umask 077
while :; do
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  target="$BACKUP_DIR/mosprom-$stamp.dump"
  pg_dump --format=custom --no-owner --no-acl --file="$target.partial"
  mv "$target.partial" "$target"
  find "$BACKUP_DIR" -type f -name 'mosprom-*.dump' -mtime +7 -delete
  sleep 21600
done
