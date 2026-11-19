# Build context is the repo root (see docker-compose.yaml), so pyproject.toml
# and uv.lock are visible. Code lives in /app, the virtualenv in /opt/venv
# (outside /app, so the dev bind mount ./backend:/app does not hide it).
FROM python:3.13-slim

ARG DEV=false
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# 1) Dependencies (cached layer; dev tools like pytest/ruff only when DEV=true)
WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project $([ "$DEV" = "true" ] || echo "--no-dev")

# 2) Project code + entrypoint (entrypoint kept outside /app so the bind mount can't replace it)
WORKDIR /app
COPY backend/ /app/
COPY backend/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh && chmod +x /usr/local/bin/entrypoint.sh \
    && DJANGO_SECRET_KEY=build-only-not-secret python manage.py collectstatic --noinput \
    && useradd --create-home app && chown -R app:app /app
USER app

EXPOSE 8000
ENTRYPOINT ["entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
