"""
URL configuration — GEC Ministère (Gestion Électronique des Courriers).
"""
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.views.generic import RedirectView, TemplateView
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),

    # Authentification Django native
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='landing'), name='logout'),

    # Application principale — courriers
    path('courrier/', include('courrier.urls')),

    # Page de garde (Landing Page)
    path('', TemplateView.as_view(template_name='landing.html'), name='landing'),
]

# Servir les fichiers médias (PDFs scannés) uniquement en développement
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
