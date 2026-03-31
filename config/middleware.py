"""Custom middleware for the pleskal."""


class ContentSecurityPolicyMiddleware:
    """
    Adds a Content-Security-Policy header to every response.

    Policy:
      - default-src 'self'
      - script-src 'self' (HTMX is vendored, no inline scripts needed)
      - style-src 'self' 'unsafe-inline' (Tailwind generates inline styles)
      - img-src 'self' data: (thumbnails served locally or from R2 via custom domain)
      - font-src 'self'
      - connect-src 'self'
      - frame-ancestors 'none' (also covered by X-Frame-Options: DENY)
      - base-uri 'self'
      - form-action 'self'

    In production, the R2 custom domain is added to img-src via the
    AWS_S3_CUSTOM_DOMAIN setting when present.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        from django.conf import settings

        r2_domain = getattr(settings, "AWS_S3_CUSTOM_DOMAIN", None)
        img_src = "'self' data:"
        if r2_domain:
            img_src = f"'self' data: https://{r2_domain}"

        csp = "; ".join(
            [
                "default-src 'self'",
                "script-src 'self'",
                "style-src 'self' 'unsafe-inline'",
                f"img-src {img_src}",
                "font-src 'self'",
                "connect-src 'self'",
                "frame-ancestors 'none'",
                "base-uri 'self'",
                "form-action 'self'",
            ]
        )
        response["Content-Security-Policy"] = csp
        response["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response
