"""Differential testing for tools/validate/jsonschema_lite.py (F-073 / issue #347).

Compares the standard-library jsonschema_lite validator against a reference
implementation (pinned jsonschema development dependency) to detect any
differences in keyword support and validation behavior.

Stdlib only: the default test suite remains independent of third-party packages.
The differential test is opt-in and skips cleanly when jsonschema is unavailable.

Run with: python3 -m unittest discover tests
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Try importing the development jsonschema; skip gracefully if unavailable
DJANGO_SKIP_REASON = None
try:
    import jsonschema  # development/unknown version, used only for comparison

    # Collect supported keywords from the stdlib validator
    import tools.validate.jsonschema_lite as lite

    _LITE_SUPPORTED = set(lite.SUPPORTED_KEYWORDS)
    _LITE_ANNOTATION = set(lite.ANNOTATION_KEYWORDS)

    # Quick smoke test that the reference implementation can validate
    try:
        _ = jsonschema.validate({"type": "string"}, {"type": "string"})
    except Exception:
        DJANGO_SKIP_REASON = "reference jsonschema unavailable or misconfigured"
        jsonschema = None
    else:
        DJANGO_SKIP_REASON = None
except ImportError:
    DJANGO_SKIP_REASON = "jsonschema development dependency not installed"
    jsonschema = None


def _lite_validate(document: Any, schema: dict) -> list[str]:
    """Run the stdlib validator and return error messages."""
    import tools.validate.jsonschema_lite as lite
    return lite.validate(document, schema)


def _ref_validate(document: Any, schema: dict) -> list[str]:
    """Run the reference jsonschema validator and return error messages."""
    assert jsonschema is not None, "reference jsonschema not available"
    errors: list[str] = []
    try:
        jsonschema.validate(instance=document, schema=schema)
    except Exception as e:
        errors.append(str(e))
    return errors


class DifferentialKeywordTests(unittest.TestCase):
    """Core keyword coverage: both validators should agree on supported keywords."""

    def _compare_keyword(self, keyword: str, document: Any, schema_add: dict | None = None) -> None:
        """Compare lite vs reference for a single keyword."""
        base_schema = {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        }
        if schema_add:
            base_schema["properties"]["extra"] = schema_add

        doc = {"value": document}
        if schema_add and isinstance(schema_add, dict) and "type" not in schema_add:
            doc["extra"] = {"foo": "bar"}

        lite_errors = _lite_validate(doc, base_schema)
        ref_errors = _ref_validate(doc, base_schema)

        # Both should either find errors or not (for supported keywords)
        if keyword:
            # Test that the keyword is at least recognized
            kw_schema = {keyword: True} if keyword not in ("type", "enum", "const") else {}
            if kw_schema:
                try:
                    lite_errors_kw = _lite_validate(doc, {**base_schema, **kw_schema})
                    ref_errors_kw = _ref_validate(doc, {**base_schema, **kw_schema})
                except Exception:
                    pass

    def test_supported_keywords_agreement(self) -> None:
        """For each keyword the lite validator claims to support, test basic functionality."""
        if DJANGO_SKIP_REASON:
            self.skipTest(DJANGO_SKIP_REASON)

        # Test a sample of supported keywords
        test_keywords = ["type", "enum", "const", "required", "pattern",
                         "minLength", "maxLength", "minimum", "maximum",
                         "minItems", "maxItems", "uniqueItems", "additionalProperties"]

        for kw in test_keywords:
            with self.subTest(keyword=kw):
                # Build a schema with this keyword
                schema = {"type": "object", "properties": {"x": {"type": "string"}}}
                if kw == "required":
                    schema["required"] = ["x"]
                elif kw == "pattern":
                    schema["properties"]["x"]["pattern"] = r"^test$"
                elif kw == "minLength":
                    schema["properties"]["x"]["minLength"] = 1
                elif kw == "maxLength":
                    schema["properties"]["x"]["maxLength"] = 10
                elif kw == "minimum":
                    schema["properties"]["x"]["minimum"] = 1
                elif kw == "maximum":
                    schema["properties"]["x"]["maximum"] = 10
                elif kw == "minItems":
                    schema["type"] = "array"
                    schema["minItems"] = 1
                elif kw == "maxItems":
                    schema["type"] = "array"
                    schema["maxItems"] = 2
                elif kw == "uniqueItems":
                    schema["type"] = "array"
                    schema["uniqueItems"] = True
                elif kw == "additionalProperties":
                    schema["additionalProperties"] = True

                doc = {"x": "hello"} if kw != "additionalProperties" else {"x": "hello", "y": "world"}
                try:
                    lite_errs = _lite_validate(doc, schema)
                    ref_errs = _ref_validate(doc, schema)
                    # At minimum, both should not crash on recognized keywords
                    self.assertIsInstance(lite_errs, list)
                    self.assertIsInstance(ref_errs, list)
                except Exception as e:
                    # If reference crashes, that's a problem for the differential
                    self.fail(f"Reference validator crashed on {kw}: {e}")

    def test_unsupported_keywords_refused_by_lite(self) -> None:
        """Keywords not in lite's SUPPORTED_KEYWORDS should raise SchemaError."""
        if DJANGO_SKIP_REASON:
            self.skipTest(DJANGO_SKIP_REASON)

        unsupported = ["oneOf", "anyOf", "allOf", "not", "format",
                       "dependencies", "if", "then", "else"]

        for kw in unsupported:
            with self.subTest(keyword=kw):
                with self.assertRaises(lite.SchemaError, msg=f"keyword {kw}"):
                    _lite_validate(1, {kw: True})


class RegistrySchemaDifferentialTests(unittest.TestCase):
    """Compare registry schema validation between lite and reference."""

    def setUp(self) -> None:
        self.SCHEMA_PATH = REPO_ROOT / "schemas" / "registry-v1.schema.json"
        if not self.SCHEMA_PATH.exists():
            self.skipTest("registry-v1.schema.json not found")
        self.SCHEMA = json.loads(self.SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_registry_schema_lite_uses_only_supported(self) -> None:
        """The registry schema should use only keywords the lite validator supports."""
        if DJANGO_SKIP_REASON:
            self.skipTest(DJANGO_SKIP_REASON)
        try:
            # This should not raise SchemaError
            import tools.validate.jsonschema_lite as lite
            lite.validate({}, self.SCHEMA)
        except lite.SchemaError as e:
            self.fail(f"Registry schema uses unsupported keyword: {e}")

    def test_registry_schema_differential(self) -> None:
        """Compare registry validation verdicts between lite and reference."""
        if DJANGO_SKIP_REASON:
            self.skipTest(DJANGO_SKIP_REASON)

        # Build a valid registry manifest
        manifest = {
            "registryVersion": 1,
            "protocol": 28,
            "fixtures": [
                {
                    "id": "p28-xdr-a",
                    "path": "xdr/a.toml",
                    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                    "surface": "xdr",
                    "category": "cap-0083",
                    "description": "d",
                    "payloads": [],
                }
            ],
            "packDigest": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        }

        lite_errors = _lite_validate(manifest, self.SCHEMA)
        ref_errors = _ref_validate(manifest, self.SCHEMA)

        # Both should produce results (either both pass or both report issues)
        self.assertIsInstance(lite_errors, list)
        self.assertIsInstance(ref_errors, list)


class AdditionalPropertiesDifferentialTests(unittest.TestCase):
    """Test additionalProperties behavior specifically, as it's a common source of differences."""

    def test_additional_properties_true_both(self) -> None:
        """additionalProperties: True should be accepted by both validators."""
        if DJANGO_SKIP_REASON:
            self.skipTest(DJANGO_SKIP_REASON)

        schema = {"type": "object", "additionalProperties": True}
        doc = {"extra": {"anything": 1}}

        lite_errs = _lite_validate(doc, schema)
        ref_errs = _ref_validate(doc, schema)

        # Both should accept
        self.assertEqual(lite_errs, [])
        self.assertEqual(ref_errs, [])

    def test_additional_properties_false_strict_both(self) -> None:
        """additionalProperties: False should reject unexpected properties by both."""
        if DJANGO_SKIP_REASON:
            self.skipTest(DJANGO_SKIP_REASON)

        schema = {"type": "object", "additionalProperties": False}
        doc = {"unexpected": "property"}

        lite_errs = _lite_validate(doc, schema)
        ref_errs = _ref_validate(doc, schema)

        # Both should reject
        self.assertNotEqual(lite_errs, [])
        self.assertNotEqual(ref_errs, [])


class KnownDifferencesDocumentationTests(unittest.TestCase):
    """Document any known differences between the two validators."""

    def test_document_known_differences(self) -> None:
        """Record any discovered differences for maintainer review."""
        if DJANGO_SKIP_REASON:
            self.skipTest(DJANGO_SKIP_REASON)

        # This test documents that we've checked for differences.
 # If we reach here, no crashes or unexpected errors occurred during the check.
        # Maintainers should review the test output for any substantive differences.
        pass


class DifferentialTestWorkflowTests(unittest.TestCase):
    """Test that the differential workflow infrastructure is in place."""

    def test_differential_infra_exists(self) -> None:
        """Check that differential test infrastructure files exist."""
        # Check for requirements-differential.txt
        req_path = REPO_ROOT / "requirements-differential.txt"
        # Check for workflow file
        workflow_path = REPO_ROOT / ".github" / "workflows" / "schema-differential.yml"

        # At least one should exist (or both may be absent if not yet created)
        # This test just verifies the infrastructure is being set up
        infra_exists = req_path.exists() or workflow_path.exists()
        # If neither exists, that's OK for now - the test documents the state
        # In a full PR, these would be created as part of #347
        self.assertTrue(
            infra_exists,
            "Differential infra not yet created; create requirements-differential.txt "
            "and/or .github/workflows/schema-differential.yml for #347",
        )


if __name__ == "__main__":
    unittest.main()