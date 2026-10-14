"""@subscribe accepts wildcard topics ("#", "user.*") without requiring a schema."""

import uuid
from typing import Any
from unittest.mock import patch

import pytest
from celery import Celery
from celery.exceptions import Ignore

from celery_salt.core.decorators import subscribe
from celery_salt.core.events import WildcardEvent
from celery_salt.core.exceptions import SchemaRegistryUnavailableError
from celery_salt.core.registry import (
    InMemorySchemaRegistry,
    get_schema_registry,
    set_schema_registry,
)
from celery_salt.integrations import registry as handler_registry_module
from celery_salt.integrations.dispatcher import create_topic_dispatcher
from celery_salt.integrations.registry import HandlerRegistry, get_handler_registry
from celery_salt.utils.json_encoder import dumps_message


class TestSubscribeWildcard:
    def setup_method(self) -> None:
        set_schema_registry(InMemorySchemaRegistry())
        handler_registry_module._global_handler_registry = HandlerRegistry()

    def test_hash_wildcard_does_not_require_a_registered_schema(self) -> None:
        @subscribe("#")
        def catch_all_handler(data):
            return "processed"

        assert callable(catch_all_handler)

    def test_hash_wildcard_passes_through_arbitrary_payload(self) -> None:
        received = {}

        @subscribe("#")
        def payload_capturing_handler(data):
            received["payload"] = data
            return "processed"

        payload_capturing_handler.run({"anything": "goes", "count": 3})

        assert received["payload"].anything == "goes"
        assert received["payload"].count == 3

    def test_hash_wildcard_registers_as_pattern_handler_matching_any_topic(
        self,
    ) -> None:
        @subscribe("#")
        def pattern_registered_handler(data):
            return "processed"

        handlers = get_handler_registry().get_handlers("literally.any.topic.at.all")
        assert len(handlers) == 1
        assert handlers[0]["function"] is pattern_registered_handler

    def test_star_wildcard_also_skips_schema_validation(self) -> None:
        @subscribe("user.*")
        def star_handler(data):
            return "processed"

        assert callable(star_handler)
        handlers = get_handler_registry().get_handlers("user.signup")
        assert len(handlers) == 1

    def test_non_wildcard_topic_without_schema_still_raises(self) -> None:
        with pytest.raises(SchemaRegistryUnavailableError):

            @subscribe("no.schema.registered.for.this.topic")
            def handler(data):
                return "processed"


class TestWildcardTopic:
    def setup_method(self) -> None:
        set_schema_registry(InMemorySchemaRegistry())
        handler_registry_module._global_handler_registry = HandlerRegistry()

    def test_handler_receives_concrete_topic(self) -> None:
        received = {}

        @subscribe("#")
        def topic_capturing_handler(event):
            received["event"] = event

        topic_capturing_handler.run(
            {"user_id": 3, "_tchu_meta": {"routing_key": "user.signup"}}
        )

        assert isinstance(received["event"], WildcardEvent)
        assert received["event"].topic == "user.signup"
        assert received["event"].user_id == 3
        assert received["event"].model_dump() == {"user_id": 3}

    def test_missing_routing_key_falls_back_to_pattern(self) -> None:
        received = {}

        @subscribe("user.*")
        def fallback_handler(event):
            received["topic"] = event.topic

        fallback_handler.run({"user_id": 3})

        assert received["topic"] == "user.*"


class TestDispatcherWithWildcard:
    def setup_method(self) -> None:
        set_schema_registry(InMemorySchemaRegistry())
        handler_registry_module._global_handler_registry = HandlerRegistry()
        self.app = Celery("wildcard_test_app")
        self.app.conf.update(task_always_eager=True, task_eager_propagates=True)

    def _dispatch(self, routing_key: str, is_rpc: bool) -> Any:
        # Unique per call: Celery reuses a task by name, and its closure holds the registry.
        dispatcher = create_topic_dispatcher(
            self.app, task_name=f"dispatch.{uuid.uuid4()}"
        )
        body = dumps_message({"user_id": 3, "_tchu_meta": {"is_rpc": is_rpc}})
        return dispatcher.run(body, routing_key=routing_key)

    def test_broadcast_passes_topic_to_wildcard_handler(self) -> None:
        @subscribe("#")
        def broadcast_handler(event):
            return "processed"

        with patch.object(broadcast_handler, "apply_async") as apply_async:
            self._dispatch("user.signup", is_rpc=False)

        (message,) = apply_async.call_args.kwargs["args"]
        assert message["_tchu_meta"]["routing_key"] == "user.signup"

    def test_rpc_matching_only_wildcard_is_ignored(self) -> None:
        @subscribe("#")
        def rpc_catch_all(event):
            return "should not answer"

        with pytest.raises(Ignore):
            self._dispatch("rpc.users.get", is_rpc=True)

    def test_rpc_with_concrete_handler_skips_wildcard(self) -> None:
        calls = []

        @subscribe("#")
        def wildcard_handler(event):
            calls.append("wildcard")

        get_schema_registry().register_schema(
            topic="rpc.users.get",
            version="v1",
            schema={"type": "object", "properties": {"user_id": {"type": "integer"}}},
            publisher_module="tests",
            publisher_class="UsersGet",
            mode="rpc",
        )

        @subscribe("rpc.users.get")
        def concrete_handler(data):
            calls.append("concrete")
            return {"ok": True}

        result = self._dispatch("rpc.users.get", is_rpc=True)

        assert calls == ["concrete"]
        assert result["results"][0]["result"] == {"ok": True}
