#!/bin/sh
set -e

# Wait for the database and apply migrations (retries while Postgres starts up)
echo "Applying database migrations..."
for i in 1 2 3 4 5 6 7 8 9 10; do
    python manage.py migrate --noinput && break
    echo "Database not ready yet, retrying in 3s... ($i/10)"
    sleep 3
done

exec "$@"
