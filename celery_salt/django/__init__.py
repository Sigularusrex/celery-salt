"""Django integration utilities for CelerySalt (optional)."""

try:
    from celery_salt.django.celery import Celery, setup_celery_queue
    from celery_salt.django.decorators import auto_publish

    __all__ = ["auto_publish", "setup_celery_queue", "Celery"]
except ImportError:
    # Django not available - these features are optional
    __all__ = []
