"""Tests for JSON encoder utilities."""

import pytest
import json
from datetime import datetime, date, time
from decimal import Decimal
from uuid import UUID, uuid4

from tchu_tchu.utils.json_encoder import (
    MessageJSONEncoder,
    dumps_message,
    loads_message,
)


class TestMessageJSONEncoder:
    """Test cases for MessageJSONEncoder."""

    def test_encode_uuid(self):
        """Test encoding UUID objects."""
        test_uuid = uuid4()
        result = json.dumps({"id": test_uuid}, cls=MessageJSONEncoder)
        parsed = json.loads(result)
        assert parsed["id"] == str(test_uuid)

    def test_encode_datetime(self):
        """Test encoding datetime objects."""
        test_datetime = datetime(2023, 1, 15, 12, 30, 45)
        result = json.dumps({"timestamp": test_datetime}, cls=MessageJSONEncoder)
        parsed = json.loads(result)
        assert parsed["timestamp"] == test_datetime.isoformat()

    def test_encode_date(self):
        """Test encoding date objects."""
        test_date = date(2023, 1, 15)
        result = json.dumps({"date": test_date}, cls=MessageJSONEncoder)
        parsed = json.loads(result)
        assert parsed["date"] == test_date.isoformat()

    def test_encode_time(self):
        """Test encoding time objects."""
        test_time = time(12, 30, 45)
        result = json.dumps({"time": test_time}, cls=MessageJSONEncoder)
        parsed = json.loads(result)
        assert parsed["time"] == test_time.isoformat()

    def test_encode_decimal(self):
        """Test encoding Decimal objects."""
        test_decimal = Decimal("10.50")
        result = json.dumps({"amount": test_decimal}, cls=MessageJSONEncoder)
        parsed = json.loads(result)
        assert parsed["amount"] == 10.5

    def test_encode_set(self):
        """Test encoding set objects."""
        test_set = {1, 2, 3}
        result = json.dumps({"items": test_set}, cls=MessageJSONEncoder)
        parsed = json.loads(result)
        assert set(parsed["items"]) == test_set

    def test_encode_bytes_utf8(self):
        """Test encoding UTF-8 bytes."""
        test_bytes = b"hello"
        result = json.dumps({"data": test_bytes}, cls=MessageJSONEncoder)
        parsed = json.loads(result)
        assert parsed["data"] == "hello"

    def test_encode_bytes_non_utf8(self):
        """Test encoding non-UTF-8 bytes (base64)."""
        test_bytes = b"\x80\x81\x82\x83"
        result = json.dumps({"data": test_bytes}, cls=MessageJSONEncoder)
        parsed = json.loads(result)
        # Should be base64 encoded
        import base64

        assert parsed["data"] == base64.b64encode(test_bytes).decode("ascii")

    def test_encode_complex_nested_structure(self):
        """Test encoding complex nested data structures."""
        test_uuid = uuid4()
        test_datetime = datetime.now()
        test_decimal = Decimal("123.45")

        data = {
            "id": test_uuid,
            "timestamp": test_datetime,
            "amount": test_decimal,
            "tags": {"python", "django", "celery"},
            "metadata": {
                "created": test_datetime,
                "items": [1, 2, 3],
            },
        }

        result = json.dumps(data, cls=MessageJSONEncoder)
        parsed = json.loads(result)

        assert parsed["id"] == str(test_uuid)
        assert parsed["timestamp"] == test_datetime.isoformat()
        assert parsed["amount"] == float(test_decimal)
        assert set(parsed["tags"]) == {"python", "django", "celery"}
        assert parsed["metadata"]["created"] == test_datetime.isoformat()


class TestDumpsLoadsMessage:
    """Test cases for dumps_message and loads_message functions."""

    def test_dumps_simple_dict(self):
        """Test dumping a simple dictionary."""
        data = {"name": "John", "age": 30}
        result = dumps_message(data)

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["name"] == "John"
        assert parsed["age"] == 30

    def test_dumps_with_special_types(self):
        """Test dumping data with special types."""
        test_uuid = uuid4()
        test_date = date.today()
        test_datetime = datetime.now()
        test_decimal = Decimal("10.50")

        data = {
            "uuid": test_uuid,
            "date": test_date,
            "datetime": test_datetime,
            "decimal": test_decimal,
            "set": {1, 2, 3},
            "bytes": b"hello",
        }

        result = dumps_message(data)
        parsed = json.loads(result)

        assert parsed["uuid"] == str(test_uuid)
        assert parsed["date"] == test_date.isoformat()
        assert parsed["datetime"] == test_datetime.isoformat()
        assert parsed["decimal"] == float(test_decimal)
        assert set(parsed["set"]) == {1, 2, 3}
        assert parsed["bytes"] == "hello"

    def test_loads_simple_json(self):
        """Test loading a simple JSON string."""
        json_str = '{"name": "John", "age": 30}'
        result = loads_message(json_str)

        assert isinstance(result, dict)
        assert result["name"] == "John"
        assert result["age"] == 30

    def test_roundtrip(self):
        """Test serialization and deserialization roundtrip."""
        original_data = {
            "id": str(uuid4()),
            "name": "Test User",
            "age": 25,
            "tags": ["python", "django"],
            "metadata": {
                "created": datetime.now().isoformat(),
                "active": True,
            },
        }

        # Serialize and deserialize
        serialized = dumps_message(original_data)
        deserialized = loads_message(serialized)

        assert deserialized == original_data

    def test_loads_invalid_json(self):
        """Test loading invalid JSON raises error."""
        invalid_json = '{"name": "John", "age":}'

        with pytest.raises(json.JSONDecodeError):
            loads_message(invalid_json)
