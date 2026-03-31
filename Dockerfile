FROM node:20-slim AS node-builder

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY static ./static
RUN npm run css:build


FROM python:3.14-slim

# Copy uv binary from official distroless image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install system dependencies including PostgreSQL client tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy dependency files and install
COPY pyproject.toml uv.lock ./
RUN UV_LINK_MODE=copy uv sync --frozen --no-dev --no-install-project

# Copy project files
COPY . .

# Copy compiled CSS from node-builder
COPY --from=node-builder /app/static/css/output.css ./static/css/output.css

# Install the project itself and collect static files
RUN UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 uv sync --frozen --no-dev && \
    uv run python manage.py collectstatic --noinput


# Ensure the venv is in PATH
ENV PATH="/app/.venv/bin:$PATH"

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:$PORT", "--workers", "2"]
