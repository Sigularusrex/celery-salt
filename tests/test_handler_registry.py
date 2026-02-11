"""Tests for HandlerRegistry - routing key to handler mappings."""

import pytest

from celery_salt.integrations.registry import HandlerRegistry


class TestHandlerRegistry:
    """Test HandlerRegistry register, get_handlers, get_handler_count."""

    def setup_method(self):
        """Fresh registry per test."""
        self.registry = HandlerRegistry()

    def test_register_and_get_handlers_exact_match(self):
        """Register handler and retrieve by exact routing key."""
        def handler():
            pass

        self.registry.register_handler("rpc.test.list", handler, name="test_handler")
        handlers = self.registry.get_handlers("rpc.test.list")
        assert len(handlers) == 1
        assert handlers[0]["name"] == "test_handler"

    def test_get_handler_count_total(self):
        """get_handler_count with no routing_key returns total count."""
        def h1():
            pass

        def h2():
            pass

        self.registry.register_handler("topic.a", h1)
        self.registry.register_handler("topic.a", h2)
        self.registry.register_handler("topic.b", h1)
        assert self.registry.get_handler_count() == 3

    def test_get_handler_count_for_routing_key(self):
        """get_handler_count(routing_key) returns count for that key without deadlock."""
        def h1():
            pass

        def h2():
            pass

        self.registry.register_handler("rpc.test.list", h1)
        self.registry.register_handler("rpc.test.list", h2)
        self.registry.register_handler("rpc.other.get", h1)

        assert self.registry.get_handler_count("rpc.test.list") == 2
        assert self.registry.get_handler_count("rpc.other.get") == 1
        assert self.registry.get_handler_count("rpc.nonexistent") == 0

    def test_get_handler_count_with_pattern_handlers(self):
        """get_handler_count with pattern-registered handlers."""
        def h1():
            pass

        self.registry.register_handler("rpc.*.list", h1)  # pattern
        self.registry.register_handler("rpc.test.list", h1)  # exact

        # "rpc.test.list" matches both pattern and exact
        assert self.registry.get_handler_count("rpc.test.list") == 2
        assert self.registry.get_handler_count("rpc.other.list") == 1  # pattern only
        assert self.registry.get_handler_count("rpc.other.get") == 0

    def test_get_all_routing_keys(self):
        """get_all_routing_keys returns registered keys."""
        def h():
            pass

        self.registry.register_handler("topic.a", h)
        self.registry.register_handler("topic.b", h)
        self.registry.register_handler("rpc.*.list", h)
        keys = self.registry.get_all_routing_keys()
        assert "topic.a" in keys
        assert "topic.b" in keys
        assert "rpc.*.list" in keys
