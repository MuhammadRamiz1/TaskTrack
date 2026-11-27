# Build context is ./backend (see docker-compose.yaml). Code lives in /app, the
# virtualenv in /opt/venv (outside /app, so the dev bind mount ./backend:/app does
# not hide it). The same image runs api (gunicorn), worker, beat and migrate.
FROM python:3.14-slim

ARG DEV=false
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /bin/uv

# 1) Dependencies (cached layer; dev tools only when DEV=true)
WORKDIR /build
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project $([ "$DEV" = "true" ] || echo "--no-dev")

# 2) Project code and entrypoint (entrypoint lives outside /app so the bind mount can't replace it)
WORKDIR /app
COPY . /app/
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh && chmod +x /usr/local/bin/entrypoint.sh \
    && mkdir -p /var/lib/tasktrack/media \
    && DJANGO_SECRET_KEY=build-only-not-secret \
       DATABASE_URL=postgres://build:build@localhost:5432/build \
       REDIS_URL=redis://localhost:6379/0 \
       python manage.py collectstatic --noinput \
    && useradd --create-home app && chown -R app:app /app /var/lib/tasktrack
USER app

EXPOSE 8000
ENTRYPOINT ["entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
