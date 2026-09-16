class SecurityHeadersMiddleware:
    """Adds defense-in-depth browser security headers."""

    CSP_POLICY = (
        "default-src 'self'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "object-src 'none'; "
        "form-action 'self'; "
        "img-src 'self' data: https://cdn.ckeditor.com; "
        "font-src 'self' https://fonts.gstatic.com https://cdn.ckeditor.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.ckeditor.com; "
        "script-src 'self' 'unsafe-inline' https://cdn.ckeditor.com; "
        "connect-src 'self'"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Content-Security-Policy", self.CSP_POLICY)
        response.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        response.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        response.setdefault("X-Download-Options", "noopen")
        response.setdefault("Referrer-Policy", "same-origin")
        if getattr(request, "user", None) and request.user.is_authenticated:
            response.setdefault("Cache-Control", "no-store, max-age=0, private")
        return response
