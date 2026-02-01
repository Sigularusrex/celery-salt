"""Django integration utilities for CelerySalt (optional)."""

default_app_config = "celery_salt.django.apps.CelerySaltDjangoConfig"

try:
    from celery_salt.django.celery import setup_celery_queue
    from celery_salt.django.decorators import auto_publish

    __all__ = ["auto_publish", "setup_celery_queue"]
except ImportError:
    # Django not available - these features are optional
    __all__ = []
