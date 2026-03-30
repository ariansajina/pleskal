FROM node:20-slim as node-builder

WORKDIR /app
COPY package*.json ./
RUN npm ci && npm run css:build


FROM python:3.14-slim

# Install system dependencies including PostgreSQL client tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy project files
COPY . .

# Copy CSS build output from node-builder
COPY --from=node-builder /app/static ./static

# Install Python dependencies
RUN pip install uv && uv sync --no-dev

# Collect static files
RUN python manage.py collectstatic --noinput

# Expose port for web service
EXPOSE 8000

# Default command (can be overridden by Railway)
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
