FROM node:20-slim AS node-builder

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY static ./static
RUN npm run css:build


FROM python:3.14-slim

# Install system dependencies including PostgreSQL client tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy project files (excluding node_modules and CSS output)
COPY . .

# Copy compiled CSS from node-builder
COPY --from=node-builder /app/static/css/output.css ./static/css/output.css

# Install Python dependencies with uv
RUN pip install uv && uv sync --no-dev

# Collect static files (use uv run to access venv)
RUN uv run python manage.py collectstatic --noinput

# Expose port for web service
EXPOSE 8000

# Default command (can be overridden by Railway)
CMD ["uv", "run", "gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
