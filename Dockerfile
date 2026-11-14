FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY pyproject.toml alembic.ini ./
COPY tracker/ tracker/
RUN pip install --no-cache-dir . && rm -rf build ./*.egg-info

# Non-root user; /app/data holds the raw XML archive (usually a bind mount).
RUN useradd --system --uid 1000 --no-create-home app \
    && mkdir -p /app/data/raw \
    && chown -R app:app /app/data
USER app

CMD ["sh", "-c", "alembic upgrade head && exec python -m tracker.cli collect"]
