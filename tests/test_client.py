"""Tests for TchuClient."""

import pytest
from unittest.mock import Mock, patch
from tchu_tchu.client import TchuClient
from tchu_tchu.producer import CeleryProducer


class TestTchuClient:
    """Test cases for TchuClient."""

    def test_init(self):
        """Test TchuClient initialization."""
        client = TchuClient()
        assert isinstance(client.producer, CeleryProducer)

    def test_init_with_custom_celery_app(self):
        """Test TchuClient with custom Celery app."""
        mock_app = Mock()
        client = TchuClient(celery_app=mock_app)
        assert client.producer.celery_app == mock_app

    @patch.object(CeleryProducer, "publish")
    def test_publish(self, mock_publish):
        """Test message publishing."""
        client = TchuClient()
        test_data = {"user_id": "123", "name": "Test User"}

        client.publish("test.topic", test_data)

        mock_publish.assert_called_once_with(routing_key="test.topic", body=test_data)

    @patch.object(CeleryProducer, "call")
    def test_call(self, mock_call):
        """Test RPC call."""
        mock_call.return_value = {"status": "success"}
        client = TchuClient()
        test_data = {"user_id": "123"}

        result = client.call("test.topic", test_data, timeout=10)

        mock_call.assert_called_once_with(
            routing_key="test.topic", body=test_data, timeout=10
        )
        assert result == {"status": "success"}

    @patch.object(CeleryProducer, "get_topic_info")
    def test_get_topic_info(self, mock_get_info):
        """Test getting topic information."""
        mock_get_info.return_value = {"topic": "test.topic", "handler_count": 2}
        client = TchuClient()

        result = client.get_topic_info("test.topic")

        mock_get_info.assert_called_once_with("test.topic")
        assert result["topic"] == "test.topic"
        assert result["handler_count"] == 2

    @patch.object(CeleryProducer, "list_topics")
    def test_list_topics(self, mock_list_topics):
        """Test listing all topics."""
        mock_list_topics.return_value = {
            "exact_topics": ["test.topic1", "test.topic2"],
            "pattern_topics": ["user.*"],
            "total_handlers": 5,
        }
        client = TchuClient()

        result = client.list_topics()

        mock_list_topics.assert_called_once()
        assert "exact_topics" in result
        assert "pattern_topics" in result
        assert result["total_handlers"] == 5
