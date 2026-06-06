"""Simple shared-password gate. Set APP_PASSWORD env var."""
from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class SharedPasswordMiddleware:
    EXEMPT = ['/login/', '/static/', '/admin/', '/health/', '/favicon.ico']

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if any(request.path.startswith(p) for p in self.EXEMPT):
            return self.get_response(request)
        if not request.session.get('app_authed'):
            return redirect(f"{reverse('login')}?next={request.path}")
        return self.get_response(request)
