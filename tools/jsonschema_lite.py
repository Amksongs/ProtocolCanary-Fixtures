"""A minimal JSON Schema validator supporting draft 2020-12 features.

This module implements a subset of JSON Schema sufficient for validating the
validator report schema (schemas/validator-report-v1.schema.json). It is not
a full JSON Schema implementation; it handles the keywords actually used by
this repository's schemas.

Supported keywords:
- ``$schema`` (only for identification; not validated)
- ``type`` (string or array of strings)
- ``properties``
- ``required``
- ``items``
- ``enum``
- ``additionalProperties`` (boolean only)
- ``$ref`` (local references only, e.g. ``#/$defs/Foo``)
- ``$defs`` / ``definitions``
- ``title``, ``description``, ``version`` (ignored, for documentation)

Not supported (will raise ``NotImplementedError`` if encountered):
- ``allOf``, ``anyOf``, ``oneOf``, ``not``
- ``pattern properties``, ``pattern``
- ``minItems``, ``maxItems``, ``uniqueItems``
- ``minimum``, ``maximum``, ``exclusiveMinimum``, ``exclusiveMaximum``
- ``minLength``, ``maxLength``, ``pattern`` (string constraints)
- ``$comment``, ``$id``, ``$vocabulary``
- Dynamic references, remote references, circular references
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ValidationError(ValueError):
    """A JSON instance failed schema validation."""

    def __init__(self, message: str, path: str = "$") -> None:
        super().__init__(message)
        self.path = path
        self.message = message

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def validate(instance: Any, schema: dict, path: str = "$") -> None:
    """Validate *instance* against *schema*.

    Raises ``ValidationError`` on the first failure.
    """
    _validate(instance, schema, path)


def _validate(instance: Any, schema: dict, path: str) -> None:
    if not isinstance(schema, dict):
        return

    # Handle ``$ref`` first (takes precedence)
    if "$ref" in schema:
        _validate_ref(instance, schema, path)
        return

    # Type checking
    if "type" in schema:
        _validate_type(instance, schema["type"], path)

    # Enum
    if "enum" in schema:
        if instance not in schema["enum"]:
            raise ValidationError(
                f"value {instance!r} not in enum {schema['enum']!r}",
                path,
            )

    # Object validation
    if isinstance(instance, dict):
        _validate_object(instance, schema, path)

    # Array validation
    if isinstance(instance, list):
        _validate_array(instance, schema, path)


def _validate_ref(instance: Any, schema: dict, path: str) -> None:
    ref = schema["$ref"]
    if not ref.startswith("#/"):
        raise NotImplementedError(f"Remote or relative $ref not supported: {ref!r}")

    # Resolve local reference
    parts = ref[2:].split("/")
    resolved = schema
    for part in parts:
        if not isinstance(resolved, dict) or part not in resolved:
            raise NotImplementedError(f"Cannot resolve $ref {ref!r}")
        resolved = resolved[part]

    _validate(instance, resolved, path)


def _validate_type(instance: Any, type_spec: Any, path: str) -> None:
    if isinstance(type_spec, str):
        expected = {type_spec}
    elif isinstance(type_spec, list):
        expected = set(type_spec)
    else:
        raise NotImplementedError(f"Invalid type spec: {type_spec!r}")

    python_type = _json_type(instance)
    if python_type not in expected:
        raise ValidationError(
            f"expected type {sorted(expected)!r}, got {python_type!r}",
            path,
        )


def _json_type(value: Any) -> str:
    """Map a Python value to a JSON Schema type name."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _validate_object(instance: dict, schema: dict, path: str) -> None:
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    additional = schema.get("additionalProperties", True)

    # Check required fields
    for field in required:
        if field not in instance:
            raise ValidationError(f"missing required property {field!r}", f"{path}/{field!r}")

    # Validate properties
    for key, value in instance.items():
        field_path = f"{path}/{key!r}"
        if key in properties:
            _validate(value, properties[key], field_path)
        elif not additional:
            raise ValidationError(f"additional property {key!r} not allowed", field_path)


def _validate_array(instance: list, schema: dict, path: str) -> None:
    items_schema = schema.get("items")
    if items_schema is not None:
        for i, item in enumerate(instance):
            _validate(item, items_schema, f"{path}/{i}")


def load_schema(path: Path | str) -> dict:
    """Load a JSON Schema from a file."""
    if isinstance(path, str):
        path = Path(path)
    return json.loads(path.read_text(encoding="utf-8"))


def validate_file(instance_path: Path | str, schema_path: Path | str) -> None:
    """Validate a JSON file against a schema file."""
    instance = json.loads(Path(instance_path).read_text(encoding="utf-8"))
    schema = load_schema(schema_path)
    validate(instance, schema)
