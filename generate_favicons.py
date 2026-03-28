#!/usr/bin/env python
from PIL import Image

src = "static/images/logo-white-bg.png"
img = Image.open(src).convert("RGBA")

img.resize((32, 32), Image.Resampling.LANCZOS).save("static/images/favicon-32x32.png")
img.resize((180, 180), Image.Resampling.LANCZOS).save(
    "static/images/apple-touch-icon.png"
)

print("Generated static/images/favicon-32x32.png")
print("Generated static/images/apple-touch-icon.png")
