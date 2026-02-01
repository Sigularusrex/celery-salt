"""
TchuClient: thin wrapper around the producer API.

Use when you want to hold a Celery app (or None) and call .publish() / .call()
without passing it every time. Compatible with @auto_publish(client=...) and
any code that prefers a client instance.
"""

from typing import Any

from celery_salt.integrations.producer import call_rpc, publish_event
from celery_salt.logging.handlers import get_logger

logger = get_logger(__name__)


class TchuClient:
    """
    Client that wraps publish_event and call_rpc with an optional Celery app.

    Usage:
        client = TchuClient()  # uses default app (e.g. from Django AppConfig)
        client.publish("user.created", {"user_id": 1, "email": "a@b.com"})

        client = TchuClient(celery_app=my_app)
        client.call("rpc.validate", {"id": 1}, timeout=10)
    """

    def __init__(self, celery_app: Any | None = None) -> None:
        self.celery_app = celery_app

    def publish(
        self,
        topic: str,
        data: dict[str, Any] | Any,
        **kwargs: Any,
    ) -> str:
        """Publish a message to a topic (fire-and-forget). Returns message ID."""
        payload = data if isinstance(data, dict) else {"data": data}
        return publish_event(
            topic=topic,
            data=payload,
            celery_app=self.celery_app,
            **kwargs,
        )

    def call(
        self,
        topic: str,
        data: dict[str, Any] | Any,
        timeout: int = 30,
        **kwargs: Any,
    ) -> Any:
        """Send RPC and wait for response."""
        payload = data if isinstance(data, dict) else {"data": data}
        return call_rpc(
            topic=topic,
            data=payload,
            timeout=timeout,
            celery_app=self.celery_app,
            **kwargs,
        )
