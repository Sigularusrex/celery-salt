"""
Version comparison utilities for CelerySalt event versioning.

Handles version string comparison for event schema versioning.
Supports simple versions (v1, v2) and semantic versions (v1.0.0, v2.0.0).

Why not use floats?
-------------------
Floats don't work for version comparison because:

1. **Can't represent 3+ part versions**: "v1.0.1" can't be a float
2. **Semantic versioning breaks**: "v1.10" as float becomes 1.1, which is < 1.2,
   but semantically 1.10 > 1.2 (because 10 > 2)
3. **Precision issues**: Float comparison can have precision problems

Instead, we parse versions into integer parts and compare element-by-element:
- "v1" -> [1]
- "v1.0.1" -> [1, 0, 1]
- "v1.10" -> [1, 10] (not 1.1!)

This is the standard approach used by pip, npm, and other package managers.
"""



def compare_versions(v1: str, v2: str) -> int:
    """
    Compare two version strings.

    Args:
        v1: First version string (e.g., "v1", "v2", "v1.0.0")
        v2: Second version string (e.g., "v1", "v2", "v1.0.0")

    Returns:
        -1 if v1 < v2
         0 if v1 == v2
         1 if v1 > v2

    Examples:
        compare_versions("v1", "v2") -> -1  # v1 < v2
        compare_versions("v2", "v1") -> 1    # v2 > v1
        compare_versions("v1", "v1") -> 0    # v1 == v1
        compare_versions("v1.0", "v1.1") -> -1  # v1.0 < v1.1
        compare_versions("v1.10", "v1.2") -> 1  # v1.10 > v1.2 (10 > 2)
        compare_versions("v10", "v2") -> 1   # v10 > v2
        compare_versions("v1.0.1", "v1.0") -> 1  # v1.0.1 > v1.0
    """
    v1_parts = _parse_version(v1)
    v2_parts = _parse_version(v2)

    # Compare parts element by element
    max_len = max(len(v1_parts), len(v2_parts))

    for i in range(max_len):
        v1_part = v1_parts[i] if i < len(v1_parts) else 0
        v2_part = v2_parts[i] if i < len(v2_parts) else 0

        if v1_part < v2_part:
            return -1
        elif v1_part > v2_part:
            return 1

    return 0


def extract_version_number(version_str: str | None) -> int:
    """
    Extract numeric version from string like 'v1', 'v2', etc.

    For simple versions like "v1", "v2", returns the number.
    For semantic versions like "v1.0.0", returns the major version number.

    Args:
        version_str: Version string (e.g., "v1", "v2", "v1.0.0", "latest", None)

    Returns:
        Integer version number (major version for semantic versions),
        or 0 for "latest" or invalid versions

    Examples:
        extract_version_number("v1") -> 1
        extract_version_number("v2") -> 2
        extract_version_number("v1.0.0") -> 1
        extract_version_number("v10") -> 10
        extract_version_number("latest") -> 0
        extract_version_number(None) -> 0
    """
    if version_str == "latest" or version_str is None:
        return 0

    parts = _parse_version(version_str)
    if parts:
        return parts[0]  # Return major version number

    return 0


def _parse_version(version_str: str) -> list[int]:
    """
    Parse a version string into a list of integers.

    Handles:
    - Simple versions: "v1" -> [1]
    - Semantic versions: "v1.0.0" -> [1, 0, 0]
    - Versions without prefix: "1.0.0" -> [1, 0, 0]

    Args:
        version_str: Version string

    Returns:
        List of version numbers, or empty list if invalid
    """
    if not version_str:
        return []

    # Remove 'v' prefix if present and strip whitespace
    version_str = version_str.strip().lstrip("vV")

    # Split by dots
    parts = version_str.split(".")

    # Convert to integers
    version_parts = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        try:
            version_parts.append(int(part))
        except ValueError:
            # Invalid version part, return empty list
            return []

    return version_parts


def is_version_compatible(
    handler_version: str | None, message_version: str | None
) -> bool:
    """
    Check if a handler version is compatible with a message version.

    A handler is compatible if it can process the message version.
    Rules:
    - Handler with specific version can process same or newer message versions (backward compatible)
    - Handler with "latest" can process all messages
    - Handler cannot process older message versions (forward incompatible)

    Args:
        handler_version: Version handler subscribes to ("v1", "v2", "latest", or None)
        message_version: Version of the message ("v1", "v2", etc., or None)

    Returns:
        True if handler should process message, False otherwise
    """
    # Normalize handler version
    if handler_version is None:
        handler_version = "latest"

    # Case 1: Message has no version (legacy/tchu-tchu compatibility)
    if message_version is None:
        # Only handlers with "latest" should receive it
        return handler_version == "latest"

    # Case 2: Handler subscribes to "latest"
    if handler_version == "latest":
        # "latest" handlers receive all messages
        return True

    # Case 3: Handler subscribes to specific version
    # Handler receives messages with same or newer versions (backward compatible)
    # Handler does NOT receive messages with older versions (forward incompatible)
    comparison = compare_versions(handler_version, message_version)
    return comparison <= 0  # handler_version <= message_version
