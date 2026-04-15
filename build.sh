#!/usr/bin/env bash
# ============================================================
# build.sh — Script de build para Render
# Render lo ejecuta automáticamente en cada deploy.
#
# En Render, configurar DOS servicios:
#   1. Web Service  → Start Command: gunicorn crackbackend.wsgi:application
#   2. Worker       → Start Command: python manage.py qcluster
#
# Ambos comparten el mismo build.sh y las mismas env vars.
# ============================================================

set -o errexit  # Salir si algún comando falla

pip install --upgrade pip
pip install -r requirements.txt

echo "==> Collecting static files..."
python manage.py collectstatic --no-input

echo "==> Running migrations..."
python manage.py migrate --verbosity 2

echo "==> Build complete."
