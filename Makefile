OWNER_URL=postgres://tasktrack_user:tasktrack_password@db:5432/tasktrack_db

up:
	docker compose up -d --build
down:
	docker compose down
logs:
	docker compose logs -f backend
migrate:
	docker compose run --rm -e DATABASE_URL=$(OWNER_URL) backend python manage.py migrate
makemigrations:
	docker compose run --rm -e DATABASE_URL=$(OWNER_URL) backend python manage.py makemigrations
test:
	docker compose run --rm -e DATABASE_URL=$(OWNER_URL) -e DJANGO_SETTINGS_MODULE=config.settings.test backend pytest
lint:
	docker compose run --rm backend sh -c "ruff check . && ruff format --check ."
shell:
	docker compose exec backend python manage.py shell