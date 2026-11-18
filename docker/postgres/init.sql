-- Runs once, on first container start, as the superuser.
--
-- Why two roles?
--   tasktrack      owns the schema and runs migrations (the "owner").
--   tasktrack_app  is what the API connects as. It is NOT a superuser and does
--                  NOT bypass Row-Level Security, so tenant isolation is
--                  enforced by the database itself, not just by app code.
--
-- DEV PASSWORD ONLY. Use a secret manager and a different password in production.

CREATE ROLE tasktrack_app
  LOGIN
  PASSWORD 'tasktrack_app_dev'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;

GRANT CONNECT ON DATABASE tasktrack TO tasktrack_app;
GRANT USAGE ON SCHEMA public TO tasktrack_app;
