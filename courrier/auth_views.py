import hashlib
import re

from django.contrib import messages
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.http import HttpResponse


class RateLimitedLoginView(LoginView):
    template_name = 'registration/login.html'
    max_attempts = 5
    window_seconds = 15 * 60
    username_pattern = re.compile(r"^[\w.@+-]{0,150}$")

    def _client_key(self):
        forwarded_for = self.request.META.get("HTTP_X_FORWARDED_FOR", "")
        ip_address = forwarded_for.split(",")[0].strip() or self.request.META.get("REMOTE_ADDR", "")
        username = self.request.POST.get("username", "").strip().lower()
        if not self.username_pattern.fullmatch(username):
            username = "__invalid_username__"
        identity = hashlib.sha256(f"{ip_address}:{username}".encode("utf-8")).hexdigest()
        return f"login-failures:{identity}"

    def dispatch(self, request, *args, **kwargs):
        if request.method == "POST":
            attempts = cache.get(self._client_key(), 0)
            if attempts >= self.max_attempts:
                return HttpResponse(
                    "Trop de tentatives de connexion. Réessayez plus tard.",
                    status=429,
                )
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        cache.delete(self._client_key())
        return super().form_valid(form)

    def form_invalid(self, form):
        key = self._client_key()
        attempts = cache.get(key, 0) + 1
        cache.set(key, attempts, self.window_seconds)
        if attempts >= self.max_attempts:
            messages.error(self.request, "Trop de tentatives échouées. Réessayez plus tard.")
        return super().form_invalid(form)
