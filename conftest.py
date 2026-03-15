import django
from django.conf import settings

# Ensure Django is set up for pytest
if not settings.configured:
    django.setup()
