"""
Compatibility client for backward compatibility with Django decorators.

This is a thin wrapper around the new producer API to maintain compatibility
with existing Django decorators and mixins.
"""

from typing import Any, Dict, Union, Optional

from celerysalt.integrations.producer import publish_event, call_rpc
from celerysalt.logging.handlers import get_logger

logger = get_logger(__name__)


class TchuClient:
    """
    Compatibility client for backward compatibility.

    This wraps the new producer API to maintain compatibility with
    Django decorators and mixins that still use the old TchuClient interface.
    """

    def __init__(self, celery_app: Optional[Any] = None) -> None:
        """
        Initialize the compatibility client.

        Args:
            celery_app: Optional Celery app instance
        """
        self.celery_app = celery_app

    def publish(self, topic: str, data: Union[Dict[str, Any], Any], **kwargs) -> None:
        """
        Publish a message to a topic (fire-and-forget).

        Args:
            topic: Topic name to publish to
            data: Message data to publish
            **kwargs: Additional arguments (ignored for compatibility)
        """
        publish_event(
            topic=topic,
            data=data if isinstance(data, dict) else {"data": data},
            celery_app=self.celery_app,
        )

    def call(
        self,
        topic: str,
        data: Union[Dict[str, Any], Any],
        timeout: int = 30,
        allow_join: bool = False,
        **kwargs,
    ) -> Any:
        """
        Send a message and wait for a response (RPC-style).

        Args:
            topic: Topic name to send to
            data: Message data to send
            timeout: Timeout in seconds to wait for response
            allow_join: Allow calling result.get() from within a task
            **kwargs: Additional arguments (ignored for compatibility)

        Returns:
            Response from the handler
        """
        return call_rpc(
            topic=topic,
            data=data if isinstance(data, dict) else {"data": data},
            timeout=timeout,
            celery_app=self.celery_app,
            allow_join=allow_join,
        )
