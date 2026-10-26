"""Tests for the validator report JSON schema.

Validates that the schema file exists, is valid JSON Schema, and that real
validator output validates against it.

Run with: python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schemas" / "validator-report-v1.schema.json"
VALIDATE_PATH = REPO_ROOT / "tools" / "validate" / "validate.py"
SCHEMA_LITE_PATH = REPO_ROOT / "tools" / "jsonschema_lite.py"

# Import the lite validator
_spec = importlib.util.spec_from_file_location("jsonschema_lite", SCHEMA_LITE_PATH)
jsonschema_lite = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["jsonschema_lite"] = jsonschema_lite
_spec.loader.exec_module(jsonschema_lite)


def run_validator_json(root: Path | None = None) -> dict:
    """Run the validator with --format json and return the parsed report."""
    cmd = [sys.executable, str(VALIDATE_PATH)]
    if root is not None:
        cmd.append(str(root))
    cmd.append("--format")
    cmd.append("json")

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
    # The validator writes JSON to stdout even on failure (it returns non-zero exit)
    return json.loads(result.stdout)


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

VALID_RPC = """
id = "p28-rpc-example"
protocol = 28
surface = "rpc"
category = "network"
description = "example"
source_reference = "https://developers.stellar.org/docs/data/apis/rpc/api-reference/methods/getNetwork"

method = "get-network"

[[assert]]
kind = "field-equals"
field = "protocolVersion"
value = 28
"""


class SchemaFileTests(unittest.TestCase):
    def test_schema_file_exists(self) -> None:
        self.assertTrue(SCHEMA_PATH.is_file(), f"Schema file not found: {SCHEMA_PATH}")

    def test_schema_is_valid_json(self) -> None:
        with SCHEMA_PATH.open(encoding="utf-8") as f:
            json.load(f)  # Raises if not valid JSON

    def test_schema_has_required_fields(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertIn("$schema", schema)
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertIn("type", schema)
        self.assertEqual(schema["type"], "object")
        self.assertIn("properties", schema)
        self.assertIn("required", schema)
        self.assertIn("version", schema["properties"])
        self.assertIn("status", schema["properties"])
        self.assertIn("roots", schema["properties"])
        self.assertIn("total_fixture_files", schema["properties"])
        self.assertIn("errors", schema["properties"])
        self.assertIn("warnings", schema["properties"])


class SchemaValidationTests(unittest.TestCase):
    def test_validates_passing_run(self) -> None:
        """Real output from a passing run validates against the schema."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_temp_toml("valid.toml", VALID_XDR, root)
            report = run_validator_json(root)

        jsonschema_lite.validate(report, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))

    def test_validates_failing_run(self) -> None:
        """Real output from a failing run validates against the schema."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Create a fixture with an invalid surface
            bad = VALID_XDR.replace('surface = "xdr"', 'surface = "wallet"')
            write_temp_toml("bad.toml", bad, root)
            report = run_validator_json(root)

        jsonschema_lite.validate(report, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))

    def test_validates_warn_run(self) -> None:
        """Real output from a run with warnings validates against the schema."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Create a fixture missing source_reference (triggers a warning)
            no_source = VALID_XDR.replace('source_reference = "CAP-0083"', "")
            write_temp_toml("no_source.toml", no_source, root)
            report = run_validator_json(root)

        jsonschema_lite.validate(report, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))

    def test_fails_on_missing_required_field(self) -> None:
        """A report missing a required field fails schema validation."""
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        bad_report = {"status": "ok", "roots": [], "total_fixture_files": 0}

        with self.assertRaises(jsonschema_lite.ValidationError) as ctx:
            jsonschema_lite.validate(bad_report, schema)
        self.assertIn("version", str(ctx.exception))

    def test_fails_on_wrong_type(self) -> None:
        """A report with a wrong type fails schema validation."""
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        bad_report = {
            "version": 1,
            "status": "ok",
            "roots": [],
            "total_fixture_files": "not-a-number",  # Should be integer
            "errors": [],
            "warnings": [],
        }

        with self.assertRaises(jsonschema_lite.ValidationError) as ctx:
            jsonschema_lite.validate(bad_report, schema)
        self.assertIn("total_fixture_files", str(ctx.exception))

    def test_schema_allows_additional_properties(self) -> None:
        """Schema allows additional properties for forward compatibility."""
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        report = {
            "version": 1,
            "status": "ok",
            "roots": [],
            "total_fixture_files": 0,
            "errors": [],
            "warnings": [],
            "unknown_future_field": "this should be allowed",
        }

        # Should not raise
        jsonschema_lite.validate(report, schema)


class SchemaContentTypeTests(unittest.TestCase):
    def test_version_field_is_integer_enum(self) -> None:
        """The version field must be an integer with enum [1]."""
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        version_prop = schema["properties"]["version"]
        self.assertEqual(version_prop["type"], "integer")
        self.assertIn("enum", version_prop)
        self.assertEqual(version_prop["enum"], [1])

    def test_status_field_has_correct_enums(self) -> None:
        """The status field must be a string with enum ['ok', 'failed']."""
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        status_prop = schema["properties"]["status"]
        self.assertEqual(status_prop["type"], "string")
        self.assertIn("enum", status_prop)
        self.assertEqual(status_prop["enum"], ["ok", "failed"])

    def test_errors_are_array_of_objects_with_path_and_message(self) -> None:
        """Errors must be an array of objects with 'path' and 'message'."""
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        errors_prop = schema["properties"]["errors"]
        self.assertEqual(errors_prop["type"], "array")
        item_schema = errors_prop["items"]
        self.assertIn("path", item_schema["required"])
        self.assertIn("message", item_schema["required"])

    def test_warnings_are_array_of_strings(self) -> None:
        """Warnings must be an array of strings."""
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        warnings_prop = schema["properties"]["warnings"]
        self.assertEqual(warnings_prop["type"], "array")
        self.assertEqual(warnings_prop["items"]["type"], "string")


if __name__ == "__main__":
    unittest.main()
