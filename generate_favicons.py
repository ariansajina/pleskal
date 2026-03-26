#!/usr/bin/env python
"""Generate favicon files from static/images/logo.png."""

from PIL import Image

src = "static/images/logo.png"
img = Image.open(src).convert("RGBA")

img.resize((32, 32), Image.Resampling.LANCZOS).save("static/images/favicon-32x32.png")
img.resize((180, 180), Image.Resampling.LANCZOS).save(
    "static/images/apple-touch-icon.png"
)

print("Generated static/images/favicon-32x32.png")
print("Generated static/images/apple-touch-icon.png")
