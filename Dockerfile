FROM mcr.microsoft.com/playwright/python:v1.45.0-jammy

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir flask-cors gunicorn

# App code
COPY app/ ./app/
COPY prompts/ ./prompts/
COPY data/ ./data/
COPY templates/ ./templates/

# Persistent dirs (Render has ephemeral fs, but mount these via disk if needed)
RUN mkdir -p /app/output /app/uploads /app/accounts /app/screenshots

ENV PYTHONUNBUFFERED=1 \
    PORT=10000 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

EXPOSE 10000

# Run Flask with gunicorn (Render expects PORT=10000)
CMD ["sh", "-c", "gunicorn -w 1 -k gthread --threads 8 -b 0.0.0.0:${PORT:-10000} 'app.web:app'"]