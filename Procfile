web: gunicorn pnl.wsgi --log-file -
release: python manage.py migrate --noinput && python manage.py seed_cogs && python manage.py collectstatic --noinput
