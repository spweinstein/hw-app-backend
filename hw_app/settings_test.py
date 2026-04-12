"""
Test settings for hw_app.

Keep production and development settings unchanged while making `manage.py test`
work without a PostgreSQL server.
"""

from .settings import *  # noqa: F401,F403


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
