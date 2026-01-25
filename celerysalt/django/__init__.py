"""Django integration utilities for CelerySalt (optional)."""

try:
    from celerysalt.django.decorators import auto_publish
    from celerysalt.django.celery import setup_celery_queue, Celery

    __all__ = ["auto_publish", "setup_celery_queue", "Celery"]
except ImportError:
    # Django not available - these features are optional
    __all__ = []
