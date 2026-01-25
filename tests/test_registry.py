"""Tests for topic registry."""

import pytest
from unittest.mock import Mock

from tchu_tchu.registry import TopicRegistry, get_registry
from tchu_tchu.utils.error_handling import SubscriptionError


class TestTopicRegistry:
    """Test cases for TopicRegistry."""

    def setup_method(self):
        """Set up test fixtures."""
        self.registry = TopicRegistry()

    def test_register_handler(self):
        """Test registering a handler."""
        handler = Mock()

        handler_id = self.registry.register_handler("test.topic", handler)

        assert handler_id is not None
        assert handler_id.startswith("handler_")

        handlers = self.registry.get_handlers("test.topic")
        assert len(handlers) == 1
        assert handlers[0]["function"] == handler
        assert handlers[0]["routing_key"] == "test.topic"

    def test_register_multiple_handlers_same_topic(self):
        """Test registering multiple handlers for the same topic."""
        handler1 = Mock()
        handler2 = Mock()

        id1 = self.registry.register_handler("test.topic", handler1)
        id2 = self.registry.register_handler("test.topic", handler2)

        assert id1 != id2

        handlers = self.registry.get_handlers("test.topic")
        assert len(handlers) == 2

        handler_functions = [h["function"] for h in handlers]
        assert handler1 in handler_functions
        assert handler2 in handler_functions

    def test_register_pattern_handler(self):
        """Test registering a pattern handler."""
        handler = Mock()

        handler_id = self.registry.register_handler("user.*", handler)

        assert handler_id is not None

        # Should match pattern
        handlers = self.registry.get_handlers("user.created")
        assert len(handlers) == 1
        assert handlers[0]["function"] == handler

        handlers = self.registry.get_handlers("user.updated")
        assert len(handlers) == 1

        # Should not match
        handlers = self.registry.get_handlers("order.created")
        assert len(handlers) == 0

    def test_pattern_matching(self):
        """Test various pattern matching scenarios."""
        handler = Mock()
        self.registry.register_handler("user.*", handler)

        # Should match
        assert len(self.registry.get_handlers("user.created")) == 1
        assert len(self.registry.get_handlers("user.updated")) == 1
        assert len(self.registry.get_handlers("user.deleted")) == 1

        # Should not match
        assert len(self.registry.get_handlers("order.created")) == 0
        assert len(self.registry.get_handlers("userinfo")) == 0

    def test_question_mark_pattern(self):
        """Test question mark wildcard pattern."""
        handler = Mock()
        self.registry.register_handler("user.?", handler)

        # Should match single character
        assert len(self.registry.get_handlers("user.a")) == 1
        assert len(self.registry.get_handlers("user.1")) == 1

        # Should not match multiple characters
        assert len(self.registry.get_handlers("user.created")) == 0
        assert len(self.registry.get_handlers("user.")) == 0

    def test_unregister_handler(self):
        """Test unregistering a handler."""
        handler = Mock()
        handler_id = self.registry.register_handler("test.topic", handler)

        # Verify handler is registered
        assert len(self.registry.get_handlers("test.topic")) == 1

        # Unregister
        success = self.registry.unregister_handler(handler_id)
        assert success is True

        # Verify handler is removed
        assert len(self.registry.get_handlers("test.topic")) == 0

    def test_unregister_nonexistent_handler(self):
        """Test unregistering a non-existent handler."""
        success = self.registry.unregister_handler("nonexistent_id")
        assert success is False

    def test_get_all_routing_keys(self):
        """Test getting all registered routing keys."""
        handler1 = Mock()
        handler2 = Mock()

        self.registry.register_handler("topic1", handler1)
        self.registry.register_handler("topic2", handler2)

        routing_keys = self.registry.get_all_routing_keys()
        assert "topic1" in routing_keys
        assert "topic2" in routing_keys

    def test_get_all_patterns(self):
        """Test getting all registered patterns."""
        handler1 = Mock()
        handler2 = Mock()

        self.registry.register_handler("user.*", handler1)
        self.registry.register_handler("order.*", handler2)

        patterns = self.registry.get_all_patterns()
        assert "user.*" in patterns
        assert "order.*" in patterns

    def test_get_handler_count(self):
        """Test getting handler counts."""
        handler1 = Mock()
        handler2 = Mock()
        handler3 = Mock()

        self.registry.register_handler("topic1", handler1)
        self.registry.register_handler("topic1", handler2)
        self.registry.register_handler("topic2", handler3)

        # Total count
        assert self.registry.get_handler_count() == 3

        # Topic-specific count
        assert self.registry.get_handler_count("topic1") == 2
        assert self.registry.get_handler_count("topic2") == 1
        assert self.registry.get_handler_count("nonexistent") == 0

    def test_clear(self):
        """Test clearing all handlers."""
        handler1 = Mock()
        handler2 = Mock()

        self.registry.register_handler("topic1", handler1)
        self.registry.register_handler("user.*", handler2)

        assert self.registry.get_handler_count() == 2

        self.registry.clear()

        assert self.registry.get_handler_count() == 0
        assert len(self.registry.get_all_routing_keys()) == 0
        assert len(self.registry.get_all_patterns()) == 0

    def test_handler_metadata(self):
        """Test storing handler metadata."""
        handler = Mock()
        metadata = {"description": "Test handler", "version": "1.0"}

        handler_id = self.registry.register_handler(
            "test.topic", handler, name="test_handler", metadata=metadata
        )

        handlers = self.registry.get_handlers("test.topic")
        assert len(handlers) == 1

        handler_info = handlers[0]
        assert handler_info["name"] == "test_handler"
        assert handler_info["metadata"] == metadata

    def test_global_registry(self):
        """Test global registry instance."""
        registry1 = get_registry()
        registry2 = get_registry()

        # Should be the same instance
        assert registry1 is registry2
