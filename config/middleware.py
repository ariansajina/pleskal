"""Custom middleware for the pleskal."""


class ContentSecurityPolicyMiddleware:
    """
    Adds a Content-Security-Policy header to every response.

    Policy:
      - default-src 'self'
      - script-src 'self' (HTMX is vendored, no inline scripts needed)
      - style-src 'self' 'unsafe-inline' (Tailwind generates inline styles)
      - img-src 'self' data: https://tile.openstreetmap.org (OSM raster tiles
        for the /map/ page are loaded directly from the tile server)
      - font-src 'self'
      - connect-src 'self' https://tile.openstreetmap.org (Leaflet may prefetch
        tiles via fetch/XHR depending on the browser)
      - frame-ancestors 'none' (also covered by X-Frame-Options: DENY)
      - frame-src https://www.openstreetmap.org (OpenStreetMap embed on event detail)
      - base-uri 'self'
      - form-action 'self'

    In production, the R2 custom domain is added to img-src via the
    AWS_S3_CUSTOM_DOMAIN setting when present.
    """

    TILE_HOST = "https://tile.openstreetmap.org"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        from django.conf import settings

        r2_domain = getattr(settings, "AWS_S3_CUSTOM_DOMAIN", None)
        img_src_parts = ["'self'", "data:", self.TILE_HOST]
        if r2_domain:
            img_src_parts.append(f"https://{r2_domain}")
        img_src = " ".join(img_src_parts)

        csp = "; ".join(
            [
                "default-src 'self'",
                "script-src 'self'",
                "style-src 'self' 'unsafe-inline'",
                f"img-src {img_src}",
                "font-src 'self'",
                f"connect-src 'self' {self.TILE_HOST}",
                "frame-ancestors 'none'",
                "frame-src https://www.openstreetmap.org",
                "base-uri 'self'",
                "form-action 'self'",
            ]
        )
        response["Content-Security-Policy"] = csp
        response["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response
