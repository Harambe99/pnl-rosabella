web: gunicorn pnl.wsgi --workers 2 --threads 4 --timeout 900 --log-file -
release: python manage.py migrate --noinput && python manage.py seed_cogs && python manage.py collectstatic --noinput
