"""
URL configuration — GEC Ministère (Gestion Électronique des Courriers).
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from courrier.auth_views import RateLimitedLoginView
from courrier.views import SecureLogoutView
from courrier.admin import secure_admin_site

urlpatterns = [
    path('admin/', secure_admin_site.urls),

    # Authentification Django native
    path('login/', RateLimitedLoginView.as_view(), name='login'),
    path('logout/', SecureLogoutView.as_view(), name='logout'),

    # Application principale — courriers
    path('courrier/', include('courrier.urls')),

    # Page de garde (Landing Page)
    path('', TemplateView.as_view(template_name='landing.html'), name='landing'),
]
