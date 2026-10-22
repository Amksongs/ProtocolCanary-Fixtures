"""Tests for tools/catalogue/generate_html.py (F-005, issue #274)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.catalogue import generate_html


class TestCatalogueGenerator(unittest.TestCase):
    def setUp(self) -> None:
        self.sample_registry = {
            "registryVersion": 1,
            "protocol": 28,
            "fixtures": [
                {
                    "id": "p28-rpc-sample",
                    "path": "rpc/sample.toml",
                    "surface": "rpc",
                    "category": "ledger",
                    "description": "Sample RPC fixture for tests",
                },
                {
                    "id": "p28-xdr-sample",
                    "path": "xdr/sample.toml",
                    "surface": "xdr",
                    "category": "encode",
                    "description": "Sample XDR fixture for tests",
                },
                {
                    "id": "p28-soroban-sample",
                    "path": "soroban/sample.toml",
                    "surface": "soroban",
                    "category": "smoke",
                    "description": "Sample Soroban fixture for tests",
                },
            ],
            "packDigest": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        }

    def test_generate_catalogue_html_structure(self) -> None:
        html = generate_html.generate_catalogue_html(self.sample_registry)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Protocol Canary Fixture Catalogue", html)
        self.assertIn("RPC Surface", html)
        self.assertIn("XDR Surface", html)
        self.assertIn("SOROBAN Surface", html)

        # Check fixture IDs and details
        self.assertIn("p28-rpc-sample", html)
        self.assertIn("ledger", html)
        self.assertIn("Sample RPC fixture for tests", html)
        self.assertIn('<a href="../protocol-28/rpc/sample.toml">rpc/sample.toml</a>', html)

        self.assertIn("p28-xdr-sample", html)
        self.assertIn("p28-soroban-sample", html)

    def test_generate_catalogue_markdown_structure(self) -> None:
        md = generate_html.generate_catalogue_markdown(self.sample_registry)
        self.assertIn("# Protocol Canary Fixture Catalogue (Protocol 28)", md)
        self.assertIn("## RPC Surface", md)
        self.assertIn("## XDR Surface", md)
        self.assertIn("## SOROBAN Surface", md)
        self.assertIn("| `p28-rpc-sample` | ledger | Sample RPC fixture for tests | [rpc/sample.toml]", md)

    def test_empty_registry_handling(self) -> None:
        """Negative test: empty registries generate appropriate placeholder text without crash."""
        empty_reg = {
            "registryVersion": 1,
            "protocol": 29,
            "fixtures": [],
            "packDigest": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        }
        html = generate_html.generate_catalogue_html(empty_reg)
        self.assertIn("No fixtures registered in this catalogue", html)
        self.assertIn("No rpc fixtures found", html)
        self.assertIn("No xdr fixtures found", html)
        self.assertIn("No soroban fixtures found", html)

        md = generate_html.generate_catalogue_markdown(empty_reg)
        self.assertIn("No fixtures registered in this catalogue", md)

    def test_missing_description_and_fields_handling(self) -> None:
        """Negative test: missing description or other fields generate placeholders without crash."""
        partial_reg = {
            "registryVersion": 1,
            "protocol": 28,
            "fixtures": [
                {
                    "id": "p28-rpc-no-desc",
                    "surface": "rpc",
                    "category": "misc",
                    # description missing
                },
                {
                    "id": "p28-xdr-empty-desc",
                    "surface": "xdr",
                    "description": "",
                    # category missing
                },
                {
                    "id": None,
                    "surface": "soroban",
                    "description": None,
                    "category": None,
                    "path": None,
                },
            ],
        }
        html = generate_html.generate_catalogue_html(partial_reg)
        self.assertIn("No description provided", html)
        self.assertIn("uncategorized", html)
        self.assertIn("unnamed-fixture", html)
        self.assertIn("No file link", html)

    def test_main_cli_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "output.html"
            code = generate_html.main(["--output", str(out_path)])
            self.assertEqual(code, 0)
            self.assertTrue(out_path.exists())
            content = out_path.read_text(encoding="utf-8")
            self.assertIn("<!DOCTYPE html>", content)
            self.assertIn("Protocol Canary Fixture Catalogue", content)


if __name__ == "__main__":
    unittest.main()
