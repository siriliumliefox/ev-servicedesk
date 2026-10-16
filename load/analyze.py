#!/usr/bin/env python3
"""Разбор прогона k6 (глава 24, ADR 0028 п. 14): report.md и report.json в каталоге результата.

  python3 load/analyze.py load/results/<время>-<сценарий>

Источники: raw.json.gz (точки метрик k6), docker_stats.jsonl (CPU и память контейнеров),
pg_top20.csv (pg_stat_statements). Считает по операциям (метка name), по минутам и по фазам
(steady/peak/recovery): число запросов, p50/p95/p99, долю ошибок. Пороги проверяет сам k6;
разбор — для отчёта главы и сравнения «до/после». Только стандартная библиотека.
"""

from __future__ import annotations

import csv
import gzip
import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def pct(values: list[float], p: float) -> float:
    """Перцентиль по ближайшему рангу; пустой список — NaN."""
    if not values:
        return math.nan
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p / 100 * len(ordered)) - 1)]


class Bucket:
    def __init__(self) -> None:
        self.durations: list[float] = []
        self.errors = 0
        self.checked = 0

    def row(self, seconds: float | None = None) -> dict:
        d = self.durations
        out = {
            "requests": len(d),
            "p50_ms": round(pct(d, 50), 1),
            "p95_ms": round(pct(d, 95), 1),
            "p99_ms": round(pct(d, 99), 1),
            "max_ms": round(max(d), 1) if d else math.nan,
            "error_rate": round(self.errors / self.checked, 4) if self.checked else 0.0,
        }
        if seconds:
            out["rps"] = round(len(d) / seconds, 1)
        return out


def timestamp(value: str) -> float:
    """Время точки k6 (наносекунды, «Z») — в секунды; fromisoformat Python 3.9 их не читает."""
    m = re.match(r"(.+T\d\d:\d\d:\d\d)(\.\d+)?(Z|[+-]\d\d:\d\d)$", value)
    if not m:
        raise ValueError(f"время k6: {value}")
    fraction = (m.group(2) or ".0")[1:7].ljust(6, "0")
    zone = "+00:00" if m.group(3) == "Z" else m.group(3)
    return datetime.fromisoformat(f"{m.group(1)}.{fraction}{zone}").timestamp()


def load_points(path: Path):
    with gzip.open(path, "rt") as f:
        for line in f:
            item = json.loads(line)
            if item.get("type") == "Point":
                yield item["metric"], item["data"]


def analyze(out: Path) -> dict:
    by_op: dict[str, Bucket] = defaultdict(Bucket)
    by_phase: dict[str, Bucket] = defaultdict(Bucket)
    by_minute: dict[int, Bucket] = defaultdict(Bucket)
    by_kind_phase: dict[str, Bucket] = defaultdict(Bucket)
    chat: list[float] = []
    start = None
    for metric, data in load_points(out / "raw.json.gz"):
        tags = data.get("tags") or {}
        t = timestamp(data["time"])
        start = t if start is None else min(start, t)
        name, phase, kind = tags.get("name", "?"), tags.get("phase", "-"), tags.get("kind", "-")
        if metric == "http_req_duration" and kind in ("read", "write"):
            v = data["value"]
            by_op[name].durations.append(v)
            by_phase[phase].durations.append(v)
            by_kind_phase[f"{kind}/{phase}"].durations.append(v)
            by_minute[int(t // 60)].durations.append(v)
        elif metric == "errors" and kind in ("read", "write", "ws", "s3", "script"):
            failed = data["value"] > 0
            for bucket in (by_op[name], by_phase[phase], by_minute[int(t // 60)]):
                bucket.checked += 1
                bucket.errors += failed
        elif metric == "chat_delivery":
            chat.append(data["value"])
    first_minute = int(start // 60) if start else 0

    def slowest(k: str) -> float:
        return -pct(by_op[k].durations, 95)

    report = {
        "operations": {k: by_op[k].row() for k in sorted(by_op, key=slowest)},
        "phases": {k: v.row() for k, v in sorted(by_phase.items())},
        "kinds": {k: v.row() for k, v in sorted(by_kind_phase.items())},
        "minutes": {m - first_minute: by_minute[m].row(60) for m in sorted(by_minute)},
        # Минуты без единого запроса посреди прогона — сон или заморозка машины (часы прыгнули):
        # такой прогон недостоверен (глава 24, 2026-10-15).
        "gaps": [
            m - first_minute
            for m in range(min(by_minute, default=0), max(by_minute, default=0))
            if m not in by_minute
        ],
        "chat_delivery_ms": {
            "count": len(chat),
            "p95": round(pct(chat, 95), 1),
            "p99": round(pct(chat, 99), 1),
        },
        "containers": containers(out / "docker_stats.jsonl"),
    }
    broadcast = out / "broadcast.csv"
    if broadcast.exists():
        report["broadcast"] = parse_broadcast(broadcast.read_text())
    summary = out / "summary.json"
    if summary.exists():
        metrics = json.loads(summary.read_text())["metrics"]
        report["thresholds"] = {
            f"{name}: {expr}": ok["ok"]
            for name, m in metrics.items()
            for expr, ok in (m.get("thresholds") or {}).items()
        }
        stale = metrics.get("stale_board_cards")
        if stale:
            report["stale_board_cards"] = stale["values"].get("count")
    return report


BROADCAST_LIMIT_SECONDS = 300  # рассылка 10 000 получателям (ADR 0028 п. 12)
BROADCAST_FIELDS = (
    "recipients",
    "deliveries",
    "delivered",
    "failed",
    "pending",
    "last_done_s",
    "median_s",
)


def parse_broadcast(csv_row: str) -> dict | None:
    """Строка load/run.sh по БД; None — публикации нет или ничего не доставлено."""
    values = csv_row.strip().split(",")
    if len(values) != len(BROADCAST_FIELDS) or not values[5]:
        return None
    # Длина сверена выше; zip(strict=) нет в Python 3.9 хоста (analyze.py — без зависимостей).
    return dict(zip(BROADCAST_FIELDS, (int(float(v)) for v in values)))  # noqa: B905


def broadcast_ok(b: dict | None) -> bool:
    return b is not None and b["pending"] == 0 and b["last_done_s"] <= BROADCAST_LIMIT_SECONDS


def containers(path: Path) -> dict:
    """Максимум CPU (% одного ядра) и памяти по сервису compose."""
    peak: dict[str, dict] = {}
    if not path.exists():
        return peak
    for line in path.read_text().splitlines():
        try:
            s = json.loads(line)["s"]
        except (json.JSONDecodeError, KeyError):
            continue
        service = re.sub(r"^ev-integration-\d+-", "", re.sub(r"-\d+$", "", s["Name"]))
        cpu = float(s["CPUPerc"].rstrip("%") or 0)
        mem = s["MemUsage"].split("/")[0].strip()
        cur = peak.setdefault(service, {"cpu_max_percent": 0.0, "mem_max": mem, "_mem": 0.0})
        cur["cpu_max_percent"] = max(cur["cpu_max_percent"], cpu)
        size = to_mib(mem)
        if size > cur["_mem"]:
            cur["_mem"], cur["mem_max"] = size, mem
    for v in peak.values():
        v.pop("_mem")
    return peak


def to_mib(value: str) -> float:
    units = {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024, "B": 1 / 1024 / 1024}
    for unit, k in units.items():
        if value.endswith(unit):
            return float(value[: -len(unit)]) * k
    return 0.0


def broadcast_line(b: dict | None) -> str:
    if b is None:
        return "FAIL  рассылка: публикации нет или ничего не доставлено"
    return (
        f"{'PASS' if broadcast_ok(b) else 'FAIL'}  рассылка: {b['deliveries']} доставок "
        f"(получателей {b['recipients']}), последняя за {b['last_done_s']} с "
        f"(половина — за {b['median_s']} с), в очереди {b['pending']}"
    )


def table(rows: dict, key: str) -> list[str]:
    if not rows:
        return []
    cols = list(next(iter(rows.values())).keys())
    lines = [f"| {key} | " + " | ".join(cols) + " |", "|" + "---|" * (len(cols) + 1)]
    lines += [f"| {k} | " + " | ".join(str(v[c]) for c in cols) + " |" for k, v in rows.items()]
    return lines


def markdown(report: dict, out: Path) -> str:
    lines = [f"# Прогон {out.name}", ""]
    if report["gaps"]:
        lines += [f"**Недостоверен:** нет запросов в минуты {report['gaps']} (сон машины).", ""]
    if "thresholds" in report:
        lines += ["## Пороги k6", ""]
        lines += [f"- {'PASS' if ok else 'FAIL'} `{k}`" for k, ok in report["thresholds"].items()]
        lines.append("")
    if "stale_board_cards" in report:
        stale = report["stale_board_cards"]
        lines += [f"Карточки, взятые другим инженером (ожидаемые 404): {stale}", ""]
    if "broadcast" in report:
        lines += [broadcast_line(report["broadcast"]), ""]
    for title, key, col in (
        ("Чтение и изменение по фазам", "kinds", "вид/фаза"),
        ("Операции (по убыванию p95)", "operations", "операция"),
        ("По минутам", "minutes", "минута"),
    ):
        lines += [f"## {title}", "", *table(report[key], col), ""]
    lines += [f"Чат WebSocket, доставка: {report['chat_delivery_ms']}", ""]
    lines += ["## Контейнеры (максимум)", "", *table(report["containers"], "сервис"), ""]
    top = out / "pg_top20.csv"
    if top.exists():
        rows = list(csv.DictReader(top.open()))[:10]
        lines += ["## pg_stat_statements, топ-10 по суммарному времени", ""]
        lines += ["| calls | total_ms | mean_ms | max_ms | query |", "|---|---|---|---|---|"]
        lines += [
            f"| {r['calls']} | {r['total_ms']} | {r['mean_ms']} | {r['max_ms']} | "
            f"`{r['query'][:160]}` |"
            for r in rows
        ]
    return "\n".join(lines) + "\n"


def main() -> int:
    out = Path(sys.argv[1])
    report = analyze(out)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    (out / "report.md").write_text(markdown(report, out))
    for k, v in report["kinds"].items():
        print(f"  {k:<22} n={v['requests']:<7} p95={v['p95_ms']} мс p99={v['p99_ms']} мс")
    for k, v in report["phases"].items():
        print(f"  ошибки {k:<15} {v['error_rate'] * 100:.2f} %")
    failed = False
    if "broadcast" in report:
        print(broadcast_line(report["broadcast"]))
        failed = not broadcast_ok(report["broadcast"])
    if report["gaps"]:
        print(f"FAIL  прогон недостоверен: нет запросов в минуты {report['gaps']} (сон машины?)")
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
