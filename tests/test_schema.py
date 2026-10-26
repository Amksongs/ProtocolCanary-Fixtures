"""Tests for the validator report JSON schema.

Validates that the schema file exists, declares a well-formed schema, and
that real `validate.py --format json` output conforms to it.

Run with: python3 -m unittest discover tests
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schemas" / "validator-report-v1.schema.json"
VALIDATE_PATH = REPO_ROOT / "tools" / "validate" / "validate.py"
SCHEMA_LITE_PATH = REPO_ROOT / "tools" / "validate" / "jsonschema_lite.py"

# Import the repository's canonical lite validator.
_spec = importlib.util.spec_from_file_location("jsonschema_lite", SCHEMA_LITE_PATH)
jsonschema_lite = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["jsonschema_lite"] = jsonschema_lite
_spec.loader.exec_module(jsonschema_lite)


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def run_validator_json(root: Path | None = None) -> dict:
    """Run the validator CLI with --format json and return the parsed report."""
    cmd = [sys.executable, str(VALIDATE_PATH)]
    if root is not None:
        cmd.append(str(root))
    cmd.append("--format")
    cmd.append("json")

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
    # The validator writes JSON to stdout even on failure (it returns non-zero exit)
    return json.loads(result.stdout)


def run_validator_json_with_warning(root: Path) -> dict:
    """Run ``validate.main`` in-process and return a report carrying a warning.

    The validator has no warning-producing path of its own today, so the
    warning is injected the way ``tests/test_validate.py`` does it: the real
    ``validate_directory`` is wrapped and one warning is added to the report
    it returns. The JSON document is still built and printed by the real
    ``--format json`` path, so what is validated below is genuine output.
    """
    spec = importlib.util.spec_from_file_location("validator_report_validate", VALIDATE_PATH)
    validate = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["validator_report_validate"] = validate
    spec.loader.exec_module(validate)

    real = validate.validate_directory

    def wrapper(directory: Path, *args, **kwargs):
        report = real(directory, *args, **kwargs)
        report.warning(directory / "injected.toml", "injected warning")
        return report

    stdout = io.StringIO()
    with mock.patch.object(validate, "validate_directory", side_effect=wrapper):
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
            validate.main(["--format", "json", str(root)])
    return json.loads(stdout.getvalue())


def write_temp_toml(name: str, contents: str, tmp_dir: Path) -> Path:
    """Write a temporary TOML fixture file."""
    path = tmp_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    return path


VALID_XDR = """
id = "p28-xdr-cap83-example"
protocol = 28
surface = "xdr"
category = "cap-0083"
description = "example"
source_reference = "CAP-0083"

type = "StellarValue"
kind = "decode-success"
value_base64 = "AAAAAA=="
"""


class SchemaFileTests(unittest.TestCase):
    def test_schema_file_exists(self) -> None:
        self.assertTrue(SCHEMA_PATH.is_file(), f"Schema file not found: {SCHEMA_PATH}")

    def test_schema_is_valid_json(self) -> None:
        with SCHEMA_PATH.open(encoding="utf-8") as f:
            json.load(f)  # Raises if not valid JSON

    def test_schema_has_required_fields(self) -> None:
        schema = load_schema()
        self.assertIn("$schema", schema)
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertIn("$id", schema)
        self.assertIn("title", schema)
        self.assertIn("type", schema)
        self.assertEqual(schema["type"], "object")
        self.assertIn("properties", schema)
        self.assertIn("required", schema)
        self.assertEqual(
            set(schema["required"]), {"valid", "errors", "warnings", "summary"}
        )
        for field in ("valid", "errors", "warnings", "summary"):
            self.assertIn(field, schema["properties"])


class SchemaValidationTests(unittest.TestCase):
    def test_validates_passing_run(self) -> None:
        """Real output from a passing run conforms to the schema."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_temp_toml("valid.toml", VALID_XDR, root)
            report = run_validator_json(root)

        self.assertTrue(report["valid"])
        self.assertEqual(report["errors"], [])
        self.assertEqual(jsonschema_lite.validate(report, load_schema()), [])

    def test_validates_failing_run(self) -> None:
        """Real output from a failing run conforms to the schema."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Create a fixture with an invalid surface
            bad = VALID_XDR.replace('surface = "xdr"', 'surface = "wallet"')
            write_temp_toml("bad.toml", bad, root)
            report = run_validator_json(root)

        self.assertFalse(report["valid"])
        self.assertTrue(report["errors"])
        self.assertEqual(jsonschema_lite.validate(report, load_schema()), [])

    def test_validates_warn_run(self) -> None:
        """Real output from a run with warnings conforms to the schema."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_temp_toml("valid.toml", VALID_XDR, root)
            report = run_validator_json_with_warning(root)

        self.assertTrue(report["warnings"])
        self.assertEqual(report["warnings"][0]["message"], "injected warning")
        # A warning is not an error: the run still reports valid.
        self.assertTrue(report["valid"])
        self.assertEqual(jsonschema_lite.validate(report, load_schema()), [])

    def test_fails_on_missing_required_field(self) -> None:
        """A report missing a required field is rejected."""
        bad_report = {
            "errors": [],
            "warnings": [],
            "summary": {"roots": [], "fixtures": 0, "errors": 0, "warnings": 0},
        }

        errors = jsonschema_lite.validate(bad_report, load_schema())
        self.assertTrue(errors)
        self.assertTrue(any("valid" in message for message in errors), errors)

    def test_fails_on_wrong_type(self) -> None:
        """A report with a wrong type is rejected."""
        bad_report = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "summary": {"roots": [], "fixtures": "not-a-number", "errors": 0, "warnings": 0},
        }

        errors = jsonschema_lite.validate(bad_report, load_schema())
        self.assertTrue(errors)
        self.assertTrue(any("fixtures" in message for message in errors), errors)

    def test_fails_on_incomplete_diagnostic(self) -> None:
        """A diagnostic missing its message field is rejected."""
        bad_report = {
            "valid": False,
            "errors": [{"path": "x.toml", "id": None, "line": None}],
            "warnings": [],
            "summary": {"roots": [], "fixtures": 1, "errors": 1, "warnings": 0},
        }

        errors = jsonschema_lite.validate(bad_report, load_schema())
        self.assertTrue(errors)
        self.assertTrue(any("message" in message for message in errors), errors)

    def test_schema_allows_additional_properties(self) -> None:
        """The schema allows additional properties for forward compatibility."""
        report = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "summary": {"roots": [], "fixtures": 0, "errors": 0, "warnings": 0},
            "unknown_future_field": "this should be allowed",
        }

        self.assertEqual(jsonschema_lite.validate(report, load_schema()), [])


class SchemaContentTypeTests(unittest.TestCase):
    def test_valid_field_is_boolean(self) -> None:
        """The valid field must be a boolean."""
        valid_prop = load_schema()["properties"]["valid"]
        self.assertEqual(valid_prop["type"], "boolean")

    def test_summary_fields_are_pinned(self) -> None:
        """The summary must declare the four derived counters."""
        summary_schema = load_schema()["properties"]["summary"]
        self.assertEqual(
            summary_schema["required"], ["roots", "fixtures", "errors", "warnings"]
        )
        self.assertEqual(summary_schema["properties"]["roots"]["items"]["type"], "string")
        for counter in ("fixtures", "errors", "warnings"):
            self.assertEqual(summary_schema["properties"][counter]["type"], "integer")

    def test_diagnostics_are_pinned(self) -> None:
        """Errors and warnings must both be the four-field diagnostic object."""
        schema = load_schema()
        diagnostic = schema["$defs"]["diagnostic"]
        self.assertEqual(
            schema["properties"]["errors"]["items"],
            {"$ref": "#/$defs/diagnostic"},
        )
        self.assertEqual(
            schema["properties"]["warnings"]["items"],
            {"$ref": "#/$defs/diagnostic"},
        )
        self.assertEqual(
            diagnostic["required"], ["path", "id", "line", "message"]
        )
        self.assertEqual(diagnostic["properties"]["path"]["type"], "string")
        self.assertEqual(diagnostic["properties"]["message"]["type"], "string")
        self.assertIn("null", diagnostic["properties"]["id"]["type"])
        self.assertIn("null", diagnostic["properties"]["line"]["type"])


if __name__ == "__main__":
    unittest.main()
