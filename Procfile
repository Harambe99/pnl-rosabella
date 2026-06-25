web: gunicorn pnl.wsgi --workers 2 --threads 4 --timeout 900 --log-file - --access-logfile - --capture-output --max-requests 500 --max-requests-jitter 50
release: python manage.py migrate --noinput && python manage.py seed_cogs && python manage.py collectstatic --noinput
