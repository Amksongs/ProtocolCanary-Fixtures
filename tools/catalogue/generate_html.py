#!/usr/bin/env python3
r"""Generate a browsable HTML fixture catalogue from registry-v1.json (F-005, issue #274).

Groups fixtures by surface (rpc, xdr, soroban) and category, generating
semantic HTML tables with links to fixture definitions.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SURFACES = ("rpc", "xdr", "soroban")


def generate_catalogue_html(
    registry_data: dict[str, Any], link_prefix: str = "../protocol-28/"
) -> str:
    """Generate a clean HTML document from registry data.

    Handles empty registries or missing fields gracefully with placeholders.
    """
    protocol = registry_data.get("protocol", "Unknown")
    fixtures = registry_data.get("fixtures", [])

    grouped: dict[str, list[dict[str, Any]]] = {s: [] for s in SURFACES}
    other_surface_fixtures: list[dict[str, Any]] = []

    for fixture in fixtures:
        surface = str(fixture.get("surface", "")).lower()
        if surface in grouped:
            grouped[surface].append(fixture)
        else:
            other_surface_fixtures.append(fixture)

    html_parts = [
        "<!DOCTYPE html>",
        "<html lang=\"en\">",
        "<head>",
        "  <meta charset=\"utf-8\">",
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        f"  <title>Protocol Canary Fixture Catalogue - Protocol {html.escape(str(protocol))}</title>",
        "  <style>",
        "    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #24292f; max-width: 1200px; margin: 0 auto; padding: 2rem 1rem; }",
        "    h1 { border-bottom: 2px solid #eaecef; padding-bottom: 0.5rem; }",
        "    h2 { margin-top: 2rem; color: #0969da; border-bottom: 1px solid #d0d7de; padding-bottom: 0.3rem; }",
        "    table { border-collapse: collapse; width: 100%; margin: 1rem 0 2rem; }",
        "    th, td { border: 1px solid #d0d7de; padding: 8px 12px; text-align: left; }",
        "    th { background-color: #f6f8fa; font-weight: 600; }",
        "    tr:nth-child(even) { background-color: #fcfcfc; }",
        "    code { font-family: ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, monospace; font-size: 0.9em; background-color: rgba(175,184,193,0.2); padding: 0.2em 0.4em; border-radius: 4px; }",
        "    .placeholder { color: #57606a; font-style: italic; }",
        "    .empty-notice { color: #57606a; font-style: italic; padding: 1rem 0; }",
        "  </style>",
        "</head>",
        "<body>",
        f"  <h1>Protocol Canary Fixture Catalogue (Protocol {html.escape(str(protocol))})</h1>",
    ]

    if not fixtures:
        html_parts.append(
            "  <p class=\"empty-notice\">No fixtures registered in this catalogue.</p>"
        )

    for surface in SURFACES:
        surface_title = surface.upper()
        surface_items = grouped[surface]
        html_parts.append(f"  <h2>{surface_title} Surface</h2>")

        if not surface_items:
            html_parts.append(
                f"  <p class=\"empty-notice\">No {html.escape(surface)} fixtures found.</p>"
            )
            continue

        html_parts.append("  <table>")
        html_parts.append(
            "    <thead>\n"
            "      <tr>\n"
            "        <th>Fixture ID</th>\n"
            "        <th>Category</th>\n"
            "        <th>Description</th>\n"
            "        <th>Link</th>\n"
            "      </tr>\n"
            "    </thead>"
        )
        html_parts.append("    <tbody>")

        for f in surface_items:
            fix_id = f.get("id") or "unnamed-fixture"
            category = f.get("category") or "uncategorized"
            description = f.get("description") or "No description provided."
            path = f.get("path")

            if path:
                href = html.escape(f"{link_prefix}{path}")
                link_html = f'<a href="{href}">{html.escape(str(path))}</a>'
            else:
                link_html = '<span class="placeholder">No file link</span>'

            html_parts.append("      <tr>")
            html_parts.append(f"        <td><code>{html.escape(str(fix_id))}</code></td>")
            html_parts.append(f"        <td>{html.escape(str(category))}</td>")
            html_parts.append(f"        <td>{html.escape(str(description))}</td>")
            html_parts.append(f"        <td>{link_html}</td>")
            html_parts.append("      </tr>")

        html_parts.append("    </tbody>")
        html_parts.append("  </table>")

    if other_surface_fixtures:
        html_parts.append("  <h2>Other Surfaces</h2>")
        html_parts.append("  <table>")
        html_parts.append(
            "    <thead>\n"
            "      <tr>\n"
            "        <th>Fixture ID</th>\n"
            "        <th>Surface</th>\n"
            "        <th>Category</th>\n"
            "        <th>Description</th>\n"
            "        <th>Link</th>\n"
            "      </tr>\n"
            "    </thead>"
        )
        html_parts.append("    <tbody>")
        for f in other_surface_fixtures:
            fix_id = f.get("id") or "unnamed-fixture"
            surface_name = f.get("surface") or "unknown"
            category = f.get("category") or "uncategorized"
            description = f.get("description") or "No description provided."
            path = f.get("path")
            if path:
                href = html.escape(f"{link_prefix}{path}")
                link_html = f'<a href="{href}">{html.escape(str(path))}</a>'
            else:
                link_html = '<span class="placeholder">No file link</span>'

            html_parts.append("      <tr>")
            html_parts.append(f"        <td><code>{html.escape(str(fix_id))}</code></td>")
            html_parts.append(f"        <td>{html.escape(str(surface_name))}</td>")
            html_parts.append(f"        <td>{html.escape(str(category))}</td>")
            html_parts.append(f"        <td>{html.escape(str(description))}</td>")
            html_parts.append(f"        <td>{link_html}</td>")
            html_parts.append("      </tr>")
        html_parts.append("    </tbody>")
        html_parts.append("  </table>")

    html_parts.extend(["</body>", "</html>\n"])
    return "\n".join(html_parts)


def generate_catalogue_markdown(
    registry_data: dict[str, Any], link_prefix: str = "../protocol-28/"
) -> str:
    """Generate Markdown tables from registry data."""
    protocol = registry_data.get("protocol", "Unknown")
    fixtures = registry_data.get("fixtures", [])

    grouped: dict[str, list[dict[str, Any]]] = {s: [] for s in SURFACES}
    for fixture in fixtures:
        surface = str(fixture.get("surface", "")).lower()
        if surface in grouped:
            grouped[surface].append(fixture)

    md_lines = [
        f"# Protocol Canary Fixture Catalogue (Protocol {protocol})\n",
    ]

    if not fixtures:
        md_lines.append("*No fixtures registered in this catalogue.*\n")

    for surface in SURFACES:
        md_lines.append(f"## {surface.upper()} Surface\n")
        items = grouped[surface]
        if not items:
            md_lines.append(f"*No {surface} fixtures registered.*\n")
            continue

        md_lines.append("| Fixture ID | Category | Description | Link |")
        md_lines.append("|---|---|---|---|")
        for f in items:
            fix_id = f.get("id") or "unnamed-fixture"
            cat = f.get("category") or "uncategorized"
            desc = f.get("description") or "No description provided."
            path = f.get("path") or ""
            link = f"[{path}]({link_prefix}{path})" if path else "No link"
            md_lines.append(f"| `{fix_id}` | {cat} | {desc} | {link} |")
        md_lines.append("")

    return "\n".join(md_lines)


def load_registry(path: Path | None) -> dict[str, Any]:
    """Load registry JSON from path or construct from protocol-28."""
    if path and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    # Fallback to generating from protocol-28 pack directory
    p28_dir = REPO_ROOT / "protocol-28"
    if p28_dir.exists():
        from tools.registry import generate as reg_gen
        files = reg_gen.scan_pack(p28_dir)
        registry = reg_gen.build_registry(files)
        return registry

    return {"registryVersion": 1, "protocol": 28, "fixtures": [], "packDigest": ""}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", nargs="?", default=None, help="Path to registry-v1.json")
    parser.add_argument("--registry", dest="registry_opt", default=None, help="Path to registry-v1.json")
    parser.add_argument(
        "--output",
        "-o",
        default=str(REPO_ROOT / "docs" / "catalogue.html"),
        help="Output HTML path (default: docs/catalogue.html)",
    )
    parser.add_argument(
        "--link-prefix",
        default="../protocol-28/",
        help="Prefix for fixture file hyperlinks",
    )
    args = parser.parse_args(argv)

    reg_path_str = args.registry_opt or args.registry
    reg_path = Path(reg_path_str) if reg_path_str else None
    data = load_registry(reg_path)

    html_content = generate_catalogue_html(data, link_prefix=args.link_prefix)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_content, encoding="utf-8")
    print(f"OK: wrote catalogue to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
