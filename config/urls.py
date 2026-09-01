"""
URL configuration — GEC Ministère (Gestion Électronique des Courriers).
"""
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.views.generic import TemplateView
from courrier.views import SecureLogoutView

urlpatterns = [
    path('admin/', admin.site.urls),

    # Authentification Django native
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', SecureLogoutView.as_view(), name='logout'),

    # Application principale — courriers
    path('courrier/', include('courrier.urls')),

    # Page de garde (Landing Page)
    path('', TemplateView.as_view(template_name='landing.html'), name='landing'),
]
