# ----------------------------
# Stage 1: Build dependencies
# ----------------------------
FROM python:3.10-slim AS builder
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

RUN pip install poetry

COPY pyproject.toml poetry.lock ./

RUN poetry config virtualenvs.in-project true \
    && poetry install --no-root --without dev

# ----------------------------
# Stage 2: Runtime image
# ----------------------------
FROM python:3.10-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY . .

COPY --from=builder /app/.venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

EXPOSE 80

CMD ["python", "app.py"]