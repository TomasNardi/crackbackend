#!/usr/bin/env bash
# ============================================================
# build.sh — Script de build para Render
# Render lo ejecuta automáticamente en cada deploy.
# ============================================================

set -o errexit  # Salir si algún comando falla

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate
