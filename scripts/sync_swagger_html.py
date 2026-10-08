#!/usr/bin/env python3
"""Встраивает docs/openapi.yaml в docs/EV_ServiceDesk_SwaggerUI.html (const OPENAPI_YAML).

Использование:
    python3 scripts/sync_swagger_html.py          # обновить HTML
    python3 scripts/sync_swagger_html.py --check  # exit 1, если HTML устарел (CI)
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "docs" / "openapi.yaml"
HTML = ROOT / "docs" / "EV_ServiceDesk_SwaggerUI.html"
PATTERN = re.compile(r'(const OPENAPI_YAML = )("(?:[^"\\]|\\.)*")(;)', re.S)


def main() -> int:
    html = HTML.read_text(encoding="utf-8")
    match = PATTERN.search(html)
    if not match:
        print(f"ERROR: const OPENAPI_YAML not found in {HTML.name}")
        return 2
    spec = SPEC.read_text(encoding="utf-8")
    if json.loads(match.group(2)) == spec:
        print("Swagger UI HTML is in sync with openapi.yaml")
        return 0
    if "--check" in sys.argv:
        print("ERROR: Swagger UI HTML is out of sync. Run: python3 scripts/sync_swagger_html.py")
        return 1
    literal = json.dumps(spec).replace("</", "<\\/")
    HTML.write_text(html[: match.start(2)] + literal + html[match.end(2) :], encoding="utf-8")
    print("Swagger UI HTML updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
