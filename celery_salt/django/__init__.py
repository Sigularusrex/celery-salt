"""Django integration utilities for CelerySalt (optional)."""

try:
    from celery_salt.django.decorators import auto_publish
    from celery_salt.django.celery import setup_celery_queue, Celery

    __all__ = ["auto_publish", "setup_celery_queue", "Celery"]
except ImportError:
    # Django not available - these features are optional
    __all__ = []
