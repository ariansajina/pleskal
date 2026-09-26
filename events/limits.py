"""Event field length limits.

Kept free of Django imports so the scrapers, which truncate scraped values to
these limits, can be imported and run standalone without configuring Django.
Changing a value needs a makemigrations.
"""

MAX_TITLE_LENGTH = 250
MAX_VENUE_LENGTH = 200
MAX_PRICE_NOTE_LENGTH = 200
MAX_SOURCE_URL_LENGTH = 200
MAX_SLUG_LENGTH = 250
