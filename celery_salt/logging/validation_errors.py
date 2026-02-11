"""Validation error formatting for observability."""

from pydantic import ValidationError


def format_validation_error(ve: ValidationError) -> dict:
    """
    Format a Pydantic ValidationError for clear logging.

    Returns a dict with:
    - summary: One-line human-readable summary (e.g. "2 validation errors")
    - errors: List of dicts with loc_path, msg, type (safe for JSON logs, no sensitive input)
    - error_count: Number of validation errors
    """
    raw_errors = ve.errors()
    error_count = len(raw_errors)

    errors = []
    for err in raw_errors:
        loc = err.get("loc", ())
        loc_path = _loc_to_path(loc)
        errors.append(
            {
                "loc": loc_path,
                "msg": err.get("msg", ""),
                "type": err.get("type", "unknown"),
            }
        )

    # Build human-readable summary
    if error_count == 1:
        e0 = errors[0]
        summary = f"{e0['loc'] or 'root'}: {e0['msg']} [type={e0['type']}]"
    else:
        parts = [f"{e['loc'] or 'root'}: {e['msg']}" for e in errors[:5]]
        if error_count > 5:
            parts.append(f"... and {error_count - 5} more")
        summary = f"{error_count} validation errors: {'; '.join(parts)}"

    return {
        "summary": summary,
        "errors": errors,
        "error_count": error_count,
    }


def _loc_to_path(loc: tuple) -> str:
    """Convert Pydantic loc tuple to readable path (e.g. 'items[0].email')."""
    if not loc:
        return "root"
    parts = []
    for x in loc:
        if isinstance(x, str):
            parts.append(x)
        elif isinstance(x, int):
            parts.append(f"[{x}]")
        else:
            parts.append(str(x))
    # Join: 'a' + '[0]' + 'b' -> 'a[0].b'
    return "".join(p if p.startswith("[") else f".{p}" for p in parts).lstrip(".")
