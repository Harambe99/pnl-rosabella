from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('daily/', views.daily_view, name='daily'),
    path('upload/', views.upload, name='upload'),
    path('cogs/', views.cogs, name='cogs'),
    path('monthly-inputs/', views.monthly_inputs, name='monthly_inputs'),
    path('history/', views.history, name='history'),
    path('readme/', views.readme, name='readme'),
    path('export/', views.export_pnl, name='export_pnl'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('health/', views.health, name='health'),
    path('wipe/', views.wipe, name='wipe'),
]
