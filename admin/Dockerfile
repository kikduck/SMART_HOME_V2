# Smart Home V2 Admin - Léger pour Ryzen 5 Pro 2400G (4C/8T)
# Image Python slim, pas de build step frontend
FROM python:3.12-slim

WORKDIR /app

# Dépendances minimales
COPY admin/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code admin
COPY admin/app.py .
COPY admin/static/ ./static/

# Knowledge, schemas, prompts (éditables en volume en prod)
COPY knowledge /app/knowledge
COPY schemas /app/schemas
COPY prompts /app/prompts
ENV SMART_HOME_BASE=/app

# Uvicorn 1 worker, pas de reload (prod)
# --host 0.0.0.0 pour accès externe
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
