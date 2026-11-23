COMPOSE = docker compose
BACKEND_RUN = $(COMPOSE) run --rm --no-deps
s ?= api

.PHONY: up down reset logs ps migrate makemigrations test test-backend test-frontend lint typecheck format schema api-client shell dbshell config

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

# Deletes all volumes: database, redis, minio, node_modules.
reset:
	$(COMPOSE) down -v

logs:
	$(COMPOSE) logs -f $(s)

ps:
	$(COMPOSE) ps

config:
	$(COMPOSE) config --quiet && echo "docker-compose.yaml is valid"

# Migrations always run as the owner role (the app role cannot create tables).
migrate:
	$(COMPOSE) run --rm migrate

makemigrations:
	$(BACKEND_RUN) api sh -c 'DATABASE_URL=$$DATABASE_OWNER_URL python manage.py makemigrations'

test: test-backend test-frontend

# pytest connects as the owner role (it creates the test database); RLS tests SET ROLE tasktrack_app.
test-backend:
	$(BACKEND_RUN) api sh -c 'DATABASE_URL=$$DATABASE_OWNER_URL DJANGO_SETTINGS_MODULE=config.settings.test pytest'

test-frontend:
	$(COMPOSE) run --rm --no-deps web npm run test

lint:
	$(BACKEND_RUN) api sh -c "ruff check . && ruff format --check ."
	$(COMPOSE) run --rm --no-deps web npm run lint

typecheck:
	$(COMPOSE) run --rm --no-deps web npx tsc --noEmit

# Export the OpenAPI schema into the frontend snapshot, then regenerate the typed client.
schema:
	$(BACKEND_RUN) -T api sh -c "python manage.py spectacular --file /tmp/openapi.json --format openapi-json --validate --fail-on-warn >/dev/null && cat /tmp/openapi.json" > frontend/openapi.json

api-client: schema
	$(COMPOSE) run --rm --no-deps web npm run -s api:types

format:
	$(BACKEND_RUN) api sh -c "ruff check --fix . && ruff format ."

shell:
	$(COMPOSE) exec api python manage.py shell

dbshell:
	$(COMPOSE) exec postgres psql -U postgres -d tasktrack
