"""Strict JSON loading for untrusted tool inputs."""
from __future__ import annotations

import json


class JSONInputError(ValueError):
    """JSON text could not be decoded safely or unambiguously."""

    def __init__(self, message: str, *, json_error: json.JSONDecodeError | None = None):
        super().__init__(message)
        self.json_error = json_error


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise JSONInputError(f"duplicate object key {key!r}")
        result[key] = value
    return result


def load_json(text: str, what: str = "JSON input"):
    """Decode JSON while rejecting duplicate keys and parser limit failures."""
    try:
        return json.loads(text, object_pairs_hook=_unique_object)
    except json.JSONDecodeError as error:
        raise JSONInputError(
            f"{what}: is not valid JSON (line {error.lineno}, column {error.colno}): "
            f"{error.msg}",
            json_error=error,
        ) from None
    except JSONInputError as error:
        raise JSONInputError(f"{what}: {error}") from None
    except RecursionError:
        raise JSONInputError(f"{what}: JSON nesting is too deep") from None
    except ValueError as error:
        raise JSONInputError(f"{what}: {error}") from None
