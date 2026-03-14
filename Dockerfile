FROM python:3.11-slim

WORKDIR /app

# Install git (needed for pip git+https dependencies)
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Copy application
COPY app/ app/

# Install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy alembic
COPY alembic/ alembic/
COPY alembic.ini .

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV NOTIFICATIONS_PORT=7711

CMD ["bash", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${NOTIFICATIONS_PORT:-7711}"]
