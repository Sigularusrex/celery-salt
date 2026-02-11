"""Tests for validation error formatting."""

import pytest
from pydantic import BaseModel, ValidationError

from celery_salt.logging.validation_errors import format_validation_error


class TestFormatValidationError:
    """Test format_validation_error output structure and content."""

    def test_single_error(self):
        """Single validation error produces correct summary and structure."""
        class Model(BaseModel):
            email: str
            age: int

        with pytest.raises(ValidationError) as exc_info:
            Model(email="a", age="not_an_int")

        result = format_validation_error(exc_info.value)
        assert result["error_count"] == 1
        assert "age" in result["summary"] or "int" in result["summary"]
        assert len(result["errors"]) == 1
        assert result["errors"][0]["msg"]
        assert result["errors"][0]["type"] != "unknown"

    def test_multiple_errors(self):
        """Multiple validation errors produce joined summary."""
        class Model(BaseModel):
            email: str
            age: int

        with pytest.raises(ValidationError) as exc_info:
            Model(email=123, age="x")  # both wrong

        result = format_validation_error(exc_info.value)
        assert result["error_count"] >= 2
        assert "validation errors" in result["summary"]
        assert len(result["errors"]) == result["error_count"]

    def test_more_than_five_errors_truncates_summary(self):
        """More than 5 errors adds '... and N more' to summary."""
        class Model(BaseModel):
            a: int
            b: int
            c: int
            d: int
            e: int
            f: int

        with pytest.raises(ValidationError) as exc_info:
            Model(a="x", b="x", c="x", d="x", e="x", f="x")

        result = format_validation_error(exc_info.value)
        assert result["error_count"] == 6
        assert "... and 1 more" in result["summary"] or "more" in result["summary"]

    def test_nested_loc_path(self):
        """Nested and indexed loc tuples produce readable paths."""
        class Item(BaseModel):
            email: str

        class Model(BaseModel):
            items: list[Item]

        with pytest.raises(ValidationError) as exc_info:
            Model(items=[{"email": 123}])  # wrong type in items[0].email

        result = format_validation_error(exc_info.value)
        assert result["error_count"] >= 1
        # Path should include items and index, e.g. items[0].email or similar
        error_locs = [e["loc"] for e in result["errors"]]
        assert any("items" in loc or "0" in loc or "email" in loc for loc in error_locs)
