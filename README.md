# TaskTrack

Internal task management and time tracking platform for MobiTising. Managers assign work, team members track time against tasks, and HR/management get daily, weekly and monthly reports. See the PRD (v1.0, 18 Nov 2026) for full requirements.

## Tech stack

| Layer | Technology |
| --- | --- |
| Backend | Django (Python 3.13), managed with [uv](https://docs.astral.sh/uv/) |
| Frontend | Next.js (Node 22) |
| Database | PostgreSQL 17 |
| Cache / queues | Redis 7 |
| Orchestration | Docker Compose |

## Repository layout

```
TaskTrack/
├── backend/                  # Django project (Docker build context)
│   ├── apps/                 # Django apps
│   │   ├── accounts/         # users, roles, auth
│   │   ├── audit/            # audit log
│   │   ├── core/             # shared base models and utilities
│   │   ├── organizations/    # organization settings
│   │   ├── projects/         # projects
│   │   └── teams/            # teams and memberships
│   ├── config/               # settings (base / dev / test), urls, wsgi
│   ├── Dockerfile
│   ├── entrypoint.sh
│   ├── manage.py
│   ├── pyproject.toml        # dependencies (uv)
│   ├── uv.lock
│   └── .python-version
├── frontend/                 # Next.js app
├── docker-compose.yaml
├── Makefile
├── .env                      # local only, never commit
└── .env.example
```

Modules live in `backend/apps/`. App configs must use the dotted path, for example `name = "apps.accounts"`.

## Getting started

### Prerequisites

- Docker and Docker Compose
- uv (optional, only for a local `backend/.venv` for editor autocomplete)

### Setup

```bash
cp .env.example .env     # then edit values
make up                  # build and start all services
docker compose ps        # all four services should be Up (db healthy)
```

### Services and ports

| Service | URL / host port | Notes |
| --- | --- | --- |
| Frontend | http://localhost:3001 | Next.js dev server |
| Backend | http://localhost:8000 | Django `runserver` with auto-reload |
| PostgreSQL | `localhost:4000` | for DBeaver, psql, etc. |
| Redis | `localhost:4001` | |

Inside the compose network, containers use service names: `db:5432`, `redis:6379`, `backend:8000`.

### Development database credentials

These are local development defaults from `docker-compose.yaml`:

- Database: `tasktrack_db`
- User: `tasktrack_user`
- Password: `tasktrack_password`

There is no default Django login. An admin user is created with `createsuperuser` once the custom user model and migrations exist (see Current status).

## Configuration

Settings are split into `backend/config/settings/` (`base.py`, `dev.py`, `test.py`).

- The database is configured only through `DATABASE_URL` (read with `environ`). There is no fallback, so a missing value fails loudly.
- `REDIS_URL` follows the same pattern.
- In Docker, `docker-compose.yaml` sets `DATABASE_URL` and `REDIS_URL` using service hostnames, and these override the root `.env`.
- The root `.env` is for tools running on the host, so use host-side ports there:

```
DATABASE_URL=postgres://tasktrack_user:tasktrack_password@localhost:4000/tasktrack_db
REDIS_URL=redis://localhost:4001/0
```

## Common commands

| Command | What it does |
| --- | --- |
| `make up` | Build and start all services |
| `make down` | Stop all services |
| `make logs` | Follow backend logs |
| `make makemigrations` | Create migrations |
| `make migrate` | Apply migrations |
| `make test` | Run pytest in the backend container |
| `make lint` | Run ruff check and format check |
| `make shell` | Open the Django shell |
| `make sync` | Recreate local `backend/.venv` with uv |

Dependencies are managed with uv from `backend/`:

```bash
cd backend
uv add <package>          # runtime dependency
uv add --dev <package>    # dev dependency
```

Rebuild the image after changing dependencies or `entrypoint.sh`: `docker compose up -d --build backend`.

## Docker notes

- The backend build context is `./backend`. The `dockerfile:` path in compose is relative to that context.
- The virtualenv lives in `/opt/venv`, outside `/app`, so the dev bind mount (`./backend:/app`) does not hide it.
- `entrypoint.sh` is copied to `/usr/local/bin/` at build time. Edits to it need an image rebuild.
- The build runs `collectstatic` with dummy `DJANGO_SECRET_KEY`, `DATABASE_URL` and `REDIS_URL` values. It never connects to a database.
- `backend/.dockerignore` excludes `.venv`, caches and `.env`.
- The container runs as the non-root user `app`.

## Current status

- Docker environment: working (Postgres, Redis, Django, Next.js).
- Automatic migrations on container start are **disabled** in `entrypoint.sh`. Run `make migrate` manually.
- **Before the first `migrate`:** define the custom user model in `accounts` and set `AUTH_USER_MODEL = "accounts.User"`. Changing it after migrations exist means resetting the database (`docker compose down -v`).

### Next steps

1. `core`: abstract `BaseModel` (primary key, `created_at`, `updated_at`)
2. `accounts`: custom `User` (email login, role, manager, timezone, working hours)
3. `organizations`: `Organization` (default timezone `Asia/Karachi`, working week)
4. `teams`: `Team`, `TeamMembership`
5. `projects`: `Project` (visibility, status, archived flag)
6. `audit`: generic `AuditLog` (actor, action, object, old/new values)
7. `make makemigrations`, then `make migrate`, then `createsuperuser`

Dependency direction: `core` ← `accounts` ← `organizations` ← `teams` ← `projects`, with `audit` depending only on `accounts`. Use `settings.AUTH_USER_MODEL` and string references to avoid circular imports.

## Troubleshooting

**`network is unreachable` pulling images (IPv6).** The host has no IPv6 route but DNS returns IPv6 first. Prefer IPv4:

```bash
echo 'precedence ::ffff:0:0/96  100' | sudo tee -a /etc/gai.conf
sudo systemctl restart docker
```

**`lookup ghcr.io ... i/o timeout`.** Flaky upstream DNS. Set public DNS in systemd-resolved (`/etc/systemd/resolved.conf.d/dns.conf` with `DNS=8.8.8.8 1.1.1.1`), then restart `systemd-resolved` and `docker`.

**`port is already allocated`.** Another process is using the port. Find it with `sudo ss -ltnp | grep :3001`, then stop it or remap the host port in `docker-compose.yaml`.

**Backend cannot connect to Postgres (`127.0.0.1:4000`).** Settings must read `DATABASE_URL`. Inside Docker the host is `db:5432`, not `localhost:4000`.

**Makefile `missing separator`.** Recipe lines must be indented with a tab, not spaces.

## Security

- Never commit `.env`. Keep placeholders in `.env.example`.
- The credentials above are for local development only.
- RBAC is enforced server-side. See the PRD for the role and permission matrix.