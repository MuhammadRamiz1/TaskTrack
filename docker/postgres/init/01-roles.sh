#!/bin/sh
# Runs once, on first start of an empty Postgres volume (docker-entrypoint-initdb.d).
#
# Roles:
#   tasktrack_owner  owns the database and every table; runs migrations and creates
#                    the pytest database. NOBYPASSRLS, but as table owner it is not
#                    subject to RLS, so it is never used by the running application.
#   tasktrack_app    runtime role for api, worker and beat. Not a superuser, not an
#                    owner, NOBYPASSRLS: every query is filtered by RLS policies.
#
# Table privileges for tasktrack_app are granted by a post_migrate handler in
# apps/common (GRANT ... ON ALL TABLES), so they also apply to the pytest database.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-SQL
    CREATE ROLE tasktrack_owner LOGIN CREATEDB NOSUPERUSER NOBYPASSRLS
        PASSWORD '${TASKTRACK_OWNER_PASSWORD}';
    CREATE ROLE tasktrack_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS
        PASSWORD '${TASKTRACK_APP_PASSWORD}';
    -- Lets tests run "SET ROLE tasktrack_app" to exercise RLS.
    GRANT tasktrack_app TO tasktrack_owner;
    CREATE DATABASE tasktrack OWNER tasktrack_owner;
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname tasktrack <<-SQL
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
    CREATE EXTENSION IF NOT EXISTS btree_gist;
    REVOKE ALL ON SCHEMA public FROM PUBLIC;
    GRANT ALL ON SCHEMA public TO tasktrack_owner;
    GRANT USAGE ON SCHEMA public TO tasktrack_app;
    ALTER DEFAULT PRIVILEGES FOR ROLE tasktrack_owner IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tasktrack_app;
    ALTER DEFAULT PRIVILEGES FOR ROLE tasktrack_owner IN SCHEMA public
        GRANT USAGE, SELECT ON SEQUENCES TO tasktrack_app;
SQL
