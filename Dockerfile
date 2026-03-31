FROM node:20-slim AS node-builder

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY static ./static
RUN npm run css:build


FROM python:3.14-slim

# Copy uv binary from official distroless image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install system dependencies for PostgreSQL client
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked,id=apt \
    apt update && \
    apt install --no-install-recommends -y \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    lsb-release

# Add the PostgreSQL PGDG apt repository
RUN echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list

# Trust the PGDG GPG key
RUN curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/postgresql.gpg

# Install PostgreSQL client 18
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked,id=apt \
    apt update && \
    apt install --no-install-recommends -y postgresql-client-18 && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# Omit development dependencies
ENV UV_NO_DEV=1

# Copy dependency files and install
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Copy project files
COPY . .

# Copy compiled CSS from node-builder
COPY --from=node-builder /app/static/css/output.css ./static/css/output.css

# Install the project itself and collect static files
RUN uv sync --frozen --no-dev && \
    uv run python manage.py collectstatic --noinput

# Ensure the venv is in PATH
ENV PATH="/app/.venv/bin:$PATH"

CMD ["/bin/bash", "-c", "gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2"]
