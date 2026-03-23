#!/usr/bin/env bash
# ============================================================
# build.sh — Script de build para Render
# Render lo ejecuta automáticamente en cada deploy.
# ============================================================

set -o errexit  # Salir si algún comando falla

pip install --upgrade pip
pip install -r requirements.txt
pip install psycopg2-binary==2.9.10

echo "==> Collecting static files..."
python manage.py collectstatic --no-input

echo "==> Running migrations..."
python manage.py migrate --verbosity 2

echo "==> Build complete."
