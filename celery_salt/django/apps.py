"""Django AppConfig: auto-wires the Celery app from CELERY_APP so .publish() and .call() work from views."""

from django.apps import AppConfig


class CelerySaltDjangoConfig(AppConfig):
    name = "celery_salt.django"
    label = "celery_salt_django"
    verbose_name = "Celery Salt (Django)"

    def ready(self) -> None:
        from django.conf import settings

        app_path = getattr(settings, "CELERY_APP", None)
        if not app_path or ":" not in app_path:
            return
        module_path, app_name = app_path.rsplit(":", 1)
        from importlib import import_module

        mod = import_module(module_path)
        app = getattr(mod, app_name, None)
        if app is not None:
            from celery_salt.integrations.producer import set_default_celery_app

            set_default_celery_app(app)
