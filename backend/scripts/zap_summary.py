"""Сводка отчётов OWASP ZAP (Глава 25, ADR 0029 п. 7): `summary.md` и код выхода.

Читает `<каталог>/*.json` (отчёты `-J` сканов zap-api-scan / zap-baseline), пишет `summary.md` —
таблица «проход × уровень» и список находок с правилом, уровнем, числом и примером адреса (без
значений параметров: строка запроса отбрасывается) — и выходит с кодом 1, если есть находки High
(«0 критичных», ADR 0029 п. 3). Подавленные правила (`security/zap/rules.tsv`, IGNORE) ZAP в отчёт
не пишет; их список с обоснованием — в отчёте главы.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

RISK = {"3": "High", "2": "Medium", "1": "Low", "0": "Informational"}


def scan_alerts(report: Path) -> list[dict]:
    data = json.loads(report.read_text(encoding="utf-8"))
    alerts = []
    for site in data.get("site", []):
        for alert in site.get("alerts", []):
            instances = alert.get("instances") or [{}]
            parts = urlsplit(instances[0].get("uri", ""))
            alerts.append(
                {
                    "plugin": alert.get("pluginid", ""),
                    "name": alert.get("alert") or alert.get("name", ""),
                    "risk": RISK.get(str(alert.get("riskcode")), "?"),
                    "count": int(alert.get("count") or len(instances)),
                    "example": f"{instances[0].get('method', '')} {parts.path}".strip(),
                }
            )
    return alerts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    args = parser.parse_args()
    reports = sorted(args.results.glob("*.json"))
    if not reports:
        print("FAIL  отчётов ZAP нет")
        return 1
    lines = ["# Сводка OWASP ZAP", "", "| Проход | High | Medium | Low | Info |"]
    lines.append("|---|---|---|---|---|")
    details = ["", "## Находки", "", "| Проход | Уровень | Правило | Находка | Число | Пример |"]
    details.append("|---|---|---|---|---|---|")
    highs = 0
    for report in reports:
        alerts = scan_alerts(report)
        by_risk = Counter(a["risk"] for a in alerts)
        highs += by_risk["High"]
        lines.append(
            f"| {report.stem} | {by_risk['High']} | {by_risk['Medium']} | {by_risk['Low']} "
            f"| {by_risk['Informational']} |"
        )
        order = list(RISK.values())
        for a in sorted(alerts, key=lambda a: (order.index(a["risk"]), a["plugin"])):
            details.append(
                f"| {report.stem} | {a['risk']} | {a['plugin']} | {a['name']} | {a['count']} "
                f"| `{a['example']}` |"
            )
    summary = "\n".join(lines + details) + "\n"
    (args.results / "summary.md").write_text(summary, encoding="utf-8")
    print(summary)
    print(("FAIL" if highs else "PASS") + f"  ZAP: находок High — {highs}")
    return 1 if highs else 0


if __name__ == "__main__":
    sys.exit(main())
