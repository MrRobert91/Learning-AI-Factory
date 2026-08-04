#!/bin/sh
set -eu

# Persistent volumes can have been created by an older image that ran as root.
# Repair their ownership before dropping privileges so SQLite can migrate and
# create its WAL files after an upgrade.
if [ "$(id -u)" = "0" ]; then
    mkdir -p /data/db /data/artifacts /data/tmp
    chown -R factory:factory /data
    exec gosu factory:factory "$@"
fi

exec "$@"
