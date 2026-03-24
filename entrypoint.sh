#!/bin/sh
set -e

echo "Aplicando migrações..."
python manage.py migrate --noinput

echo "Populando base de dados..."
python manage.py seed
y

echo "Iniciando servidor HTTP..."
exec python manage.py runserver 0.0.0.0:8000
