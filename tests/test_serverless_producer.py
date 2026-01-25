"""Tests for serverless producer (serverless environments)."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from tchu_tchu.serverless_producer import ServerlessProducer, ServerlessClient
from tchu_tchu.utils.error_handling import PublishError


class TestServerlessProducer:
    """Test ServerlessProducer class."""

    def test_init(self):
        """Test producer initialization."""
        producer = ServerlessProducer(
            broker_url="amqp://user:pass@localhost:5672//",
            exchange_name="test_exchange",
            connection_timeout=5,
        )
        assert producer.broker_url == "amqp://user:pass@localhost:5672//"
        assert producer.exchange_name == "test_exchange"
        assert producer.connection_timeout == 5

    def test_parse_broker_url(self):
        """Test broker URL parsing."""
        producer = ServerlessProducer(
            broker_url="amqp://testuser:testpass@testhost:5673/testvhost"
        )
        params = producer._parse_broker_url()

        assert params.host == "testhost"
        assert params.port == 5673
        assert params.virtual_host == "testvhost"
        assert params.credentials.username == "testuser"
        assert params.credentials.password == "testpass"

    def test_parse_broker_url_defaults(self):
        """Test broker URL parsing with defaults."""
        producer = ServerlessProducer(broker_url="amqp://localhost")
        params = producer._parse_broker_url()

        assert params.host == "localhost"
        assert params.port == 5672
        assert params.virtual_host == "/"
        assert params.credentials.username == "guest"
        assert params.credentials.password == "guest"

    @patch("tchu_tchu.serverless_producer.pika.BlockingConnection")
    def test_ensure_connection(self, mock_connection_class):
        """Test connection establishment."""
        mock_connection = Mock()
        mock_channel = Mock()
        mock_connection.channel.return_value = mock_channel
        mock_connection_class.return_value = mock_connection

        producer = ServerlessProducer(broker_url="amqp://localhost")
        producer._ensure_connection()

        # Verify connection was created
        mock_connection_class.assert_called_once()
        mock_connection.channel.assert_called_once()

        # Verify exchange was declared
        mock_channel.exchange_declare.assert_called_once_with(
            exchange="tchu_events",
            exchange_type="topic",
            durable=True,
        )

    @patch("tchu_tchu.serverless_producer.pika.BlockingConnection")
    def test_publish_success(self, mock_connection_class):
        """Test successful message publishing."""
        mock_connection = Mock()
        mock_channel = Mock()
        mock_connection.is_closed = False
        mock_connection.channel.return_value = mock_channel
        mock_channel.is_open = True
        mock_connection_class.return_value = mock_connection

        producer = ServerlessProducer(broker_url="amqp://localhost")

        # Publish message
        message_id = producer.publish(
            routing_key="test.event",
            body={"test": "data"},
        )

        # Verify message was published
        assert message_id is not None
        mock_channel.basic_publish.assert_called_once()

        # Check publish arguments
        call_args = mock_channel.basic_publish.call_args
        assert call_args[1]["exchange"] == "tchu_events"
        assert call_args[1]["routing_key"] == "test.event"
        assert b'"test": "data"' in call_args[1]["body"]

    @patch("tchu_tchu.serverless_producer.pika.BlockingConnection")
    def test_publish_with_string_body(self, mock_connection_class):
        """Test publishing with string body."""
        mock_connection = Mock()
        mock_channel = Mock()
        mock_connection.is_closed = False
        mock_connection.channel.return_value = mock_channel
        mock_channel.is_open = True
        mock_connection_class.return_value = mock_connection

        producer = ServerlessProducer(broker_url="amqp://localhost")

        # Publish string message
        message_id = producer.publish(
            routing_key="test.event",
            body="test message",
        )

        assert message_id is not None
        mock_channel.basic_publish.assert_called_once()

        # Check body was encoded
        call_args = mock_channel.basic_publish.call_args
        assert call_args[1]["body"] == b"test message"

    @patch("tchu_tchu.serverless_producer.pika.BlockingConnection")
    def test_publish_connection_error(self, mock_connection_class):
        """Test publish with connection error."""
        mock_connection_class.side_effect = Exception("Connection failed")

        producer = ServerlessProducer(broker_url="amqp://localhost")

        with pytest.raises(PublishError) as exc_info:
            producer.publish(routing_key="test.event", body={"test": "data"})

        assert "Failed to connect to RabbitMQ" in str(exc_info.value)

    @patch("tchu_tchu.serverless_producer.pika.BlockingConnection")
    def test_close(self, mock_connection_class):
        """Test connection closing."""
        mock_connection = Mock()
        mock_channel = Mock()
        mock_connection.channel.return_value = mock_channel
        mock_channel.is_open = True
        mock_connection.is_open = True
        mock_connection_class.return_value = mock_connection

        producer = ServerlessProducer(broker_url="amqp://localhost")
        producer._ensure_connection()
        producer.close()

        mock_channel.close.assert_called_once()
        mock_connection.close.assert_called_once()

    @patch("tchu_tchu.serverless_producer.pika.BlockingConnection")
    def test_context_manager(self, mock_connection_class):
        """Test context manager usage."""
        mock_connection = Mock()
        mock_channel = Mock()
        mock_connection.channel.return_value = mock_channel
        mock_channel.is_open = True
        mock_connection.is_open = True
        mock_connection.is_closed = False
        mock_connection_class.return_value = mock_connection

        with ServerlessProducer(broker_url="amqp://localhost") as producer:
            producer.publish(routing_key="test.event", body={"test": "data"})

        # Verify connection was closed
        mock_channel.close.assert_called()
        mock_connection.close.assert_called()


class TestServerlessClient:
    """Test ServerlessClient class."""

    @patch("tchu_tchu.serverless_producer.pika.BlockingConnection")
    def test_init(self, mock_connection_class):
        """Test client initialization."""
        client = ServerlessClient(
            broker_url="amqp://localhost",
            exchange_name="test_exchange",
            connection_timeout=5,
        )
        assert client.producer.broker_url == "amqp://localhost"
        assert client.producer.exchange_name == "test_exchange"
        assert client.producer.connection_timeout == 5

    @patch("tchu_tchu.serverless_producer.pika.BlockingConnection")
    def test_publish(self, mock_connection_class):
        """Test client publish method."""
        mock_connection = Mock()
        mock_channel = Mock()
        mock_connection.is_closed = False
        mock_connection.channel.return_value = mock_channel
        mock_channel.is_open = True
        mock_connection_class.return_value = mock_connection

        client = ServerlessClient(broker_url="amqp://localhost")
        client.publish(topic="user.created", data={"user_id": 123})

        # Verify publish was called
        mock_channel.basic_publish.assert_called_once()
        call_args = mock_channel.basic_publish.call_args
        assert call_args[1]["routing_key"] == "user.created"

    @patch("tchu_tchu.serverless_producer.pika.BlockingConnection")
    def test_context_manager(self, mock_connection_class):
        """Test client context manager usage."""
        mock_connection = Mock()
        mock_channel = Mock()
        mock_connection.channel.return_value = mock_channel
        mock_channel.is_open = True
        mock_connection.is_open = True
        mock_connection.is_closed = False
        mock_connection_class.return_value = mock_connection

        with ServerlessClient(broker_url="amqp://localhost") as client:
            client.publish(topic="test.event", data={"test": "data"})

        # Verify connection was closed
        mock_channel.close.assert_called()
        mock_connection.close.assert_called()

    @patch("tchu_tchu.serverless_producer.pika.BlockingConnection")
    def test_close(self, mock_connection_class):
        """Test client close method."""
        mock_connection = Mock()
        mock_channel = Mock()
        mock_connection.channel.return_value = mock_channel
        mock_channel.is_open = True
        mock_connection.is_open = True
        mock_connection_class.return_value = mock_connection

        client = ServerlessClient(broker_url="amqp://localhost")
        client.producer._ensure_connection()
        client.close()

        mock_channel.close.assert_called_once()
        mock_connection.close.assert_called_once()
