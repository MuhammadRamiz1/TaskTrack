#!/bin/sh
# Migrations run in the dedicated "migrate" compose service (as the owner role),
# never here: the runtime role cannot create tables.
set -e
exec "$@"
