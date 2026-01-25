"""Tests for version comparison utilities."""


from celery_salt.core.versioning import (
    _parse_version,
    compare_versions,
    extract_version_number,
    is_version_compatible,
)


class TestParseVersion:
    """Test version parsing."""

    def test_parse_simple_version(self):
        """Test parsing simple versions like 'v1', 'v2'."""
        assert _parse_version("v1") == [1]
        assert _parse_version("v2") == [2]
        assert _parse_version("v10") == [10]

    def test_parse_semantic_version(self):
        """Test parsing semantic versions like 'v1.0.0'."""
        assert _parse_version("v1.0.0") == [1, 0, 0]
        assert _parse_version("v1.0.1") == [1, 0, 1]
        assert _parse_version("v2.0.0") == [2, 0, 0]

    def test_parse_version_without_prefix(self):
        """Test parsing versions without 'v' prefix."""
        assert _parse_version("1") == [1]
        assert _parse_version("1.0.0") == [1, 0, 0]
        assert _parse_version("2.5.3") == [2, 5, 3]

    def test_parse_version_case_insensitive(self):
        """Test parsing versions with uppercase 'V'."""
        assert _parse_version("V1") == [1]
        assert _parse_version("V1.0.0") == [1, 0, 0]

    def test_parse_invalid_version(self):
        """Test parsing invalid versions."""
        assert _parse_version("") == []
        assert _parse_version("invalid") == []
        assert _parse_version("v1.2.3.4.5.invalid") == []

    def test_parse_version_with_whitespace(self):
        """Test parsing versions with whitespace."""
        assert _parse_version("v1.0.1") == [1, 0, 1]
        assert _parse_version(" v1.0.1 ") == [1, 0, 1]


class TestCompareVersions:
    """Test version comparison."""

    def test_compare_simple_versions(self):
        """Test comparing simple versions."""
        assert compare_versions("v1", "v2") == -1  # v1 < v2
        assert compare_versions("v2", "v1") == 1  # v2 > v1
        assert compare_versions("v1", "v1") == 0  # v1 == v1
        assert compare_versions("v10", "v2") == 1  # v10 > v2

    def test_compare_semantic_versions(self):
        """Test comparing semantic versions."""
        assert compare_versions("v1.0", "v1.1") == -1  # v1.0 < v1.1
        assert compare_versions("v1.1", "v1.0") == 1  # v1.1 > v1.0
        assert compare_versions("v1.0", "v1.0") == 0  # v1.0 == v1.0
        assert compare_versions("v1.0.1", "v1.0") == 1  # v1.0.1 > v1.0

    def test_compare_semantic_version_edge_cases(self):
        """Test edge cases in semantic version comparison."""
        # v1.10 > v1.2 (because 10 > 2, not 1.1 < 1.2)
        assert compare_versions("v1.10", "v1.2") == 1
        assert compare_versions("v1.2", "v1.10") == -1

        # v2.0.0 > v1.9.9
        assert compare_versions("v2.0.0", "v1.9.9") == 1
        assert compare_versions("v1.9.9", "v2.0.0") == -1

    def test_compare_different_length_versions(self):
        """Test comparing versions with different lengths."""
        # v1.0.0 == v1.0 (missing parts treated as 0)
        assert compare_versions("v1.0.0", "v1.0") == 0
        assert compare_versions("v1.0", "v1.0.0") == 0

        # v1.0.1 > v1.0
        assert compare_versions("v1.0.1", "v1.0") == 1
        assert compare_versions("v1.0", "v1.0.1") == -1

    def test_compare_versions_without_prefix(self):
        """Test comparing versions without 'v' prefix."""
        assert compare_versions("1", "2") == -1
        assert compare_versions("1.0.0", "1.0.1") == -1


class TestExtractVersionNumber:
    """Test version number extraction."""

    def test_extract_simple_version(self):
        """Test extracting from simple versions."""
        assert extract_version_number("v1") == 1
        assert extract_version_number("v2") == 2
        assert extract_version_number("v10") == 10

    def test_extract_semantic_version(self):
        """Test extracting from semantic versions (returns major version)."""
        assert extract_version_number("v1.0.0") == 1
        assert extract_version_number("v2.5.3") == 2
        assert extract_version_number("v10.0.0") == 10

    def test_extract_latest_version(self):
        """Test extracting from 'latest'."""
        assert extract_version_number("latest") == 0
        assert extract_version_number(None) == 0

    def test_extract_invalid_version(self):
        """Test extracting from invalid versions."""
        assert extract_version_number("invalid") == 0
        assert extract_version_number("") == 0


class TestIsVersionCompatible:
    """Test version compatibility checking."""

    def test_same_version_compatible(self):
        """Test that same versions are compatible."""
        assert is_version_compatible("v1", "v1") is True
        assert is_version_compatible("v2", "v2") is True
        assert is_version_compatible("v1.0.0", "v1.0.0") is True

    def test_newer_message_version_compatible(self):
        """Test that handlers can process newer message versions (backward compatible)."""
        # v1 handler can process v2 messages
        assert is_version_compatible("v1", "v2") is True
        # v1 handler can process v3 messages
        assert is_version_compatible("v1", "v3") is True
        # v1.0 handler can process v1.1 messages
        assert is_version_compatible("v1.0", "v1.1") is True

    def test_older_message_version_incompatible(self):
        """Test handlers cannot process older message versions (forward incompatible)."""
        # v2 handler cannot process v1 messages
        assert is_version_compatible("v2", "v1") is False
        # v1.1 handler cannot process v1.0 messages
        assert is_version_compatible("v1.1", "v1.0") is False

    def test_latest_handler_compatible(self):
        """Test that 'latest' handlers are compatible with all messages."""
        assert is_version_compatible("latest", "v1") is True
        assert is_version_compatible("latest", "v2") is True
        assert is_version_compatible("latest", "v10") is True
        assert is_version_compatible("latest", None) is True

    def test_none_handler_defaults_to_latest(self):
        """Test that None handler version defaults to 'latest'."""
        assert is_version_compatible(None, "v1") is True
        assert is_version_compatible(None, "v2") is True
        assert is_version_compatible(None, None) is True

    def test_legacy_message_without_version(self):
        """Test compatibility with legacy messages (no version)."""
        # Only 'latest' handlers can process messages without version
        assert is_version_compatible("latest", None) is True
        assert is_version_compatible(None, None) is True
        # Specific version handlers cannot process messages without version
        assert is_version_compatible("v1", None) is False
        assert is_version_compatible("v2", None) is False

    def test_semantic_version_compatibility(self):
        """Test compatibility with semantic versions."""
        # v1.0 handler can process v1.1 messages
        assert is_version_compatible("v1.0", "v1.1") is True
        # v1.0 handler can process v2.0 messages
        assert is_version_compatible("v1.0", "v2.0") is True
        # v1.1 handler cannot process v1.0 messages
        assert is_version_compatible("v1.1", "v1.0") is False
