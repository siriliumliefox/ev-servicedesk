"""Проверка дерева решений на тупики (ADR 0018 п. 3–4) — чистая функция без БД.

Типы узлов: вопрос — от одного варианта; решение («проблема решена») — без вариантов и не
эскалация; эскалация — `is_escalation`, варианты допустимы. Финал — решение или эскалация.
Тупик (`DEAD_END`) — узел, из которого не достижим ни один финал, в том числе замкнутый цикл
вопросов. Узлы, недостижимые из корня, — `UNREACHABLE`; дереву нужна хотя бы одна
достижимая эскалация — `NO_ESCALATION` (C-07: переход в тикет).
"""

import enum
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass


class TreeProblem(enum.StrEnum):
    NO_ROOT = "NO_ROOT"
    MULTIPLE_ROOTS = "MULTIPLE_ROOTS"
    BROKEN_REFERENCE = "BROKEN_REFERENCE"
    UNREACHABLE = "UNREACHABLE"
    DEAD_END = "DEAD_END"
    NO_ESCALATION = "NO_ESCALATION"


@dataclass(frozen=True)
class TreeNode:
    id: int
    next_ids: tuple[int, ...]  # next_node_id вариантов по порядку
    is_root: bool = False
    is_escalation: bool = False

    @property
    def is_final(self) -> bool:
        """Решение (нет вариантов) или эскалация — клиенту есть чем закончить."""
        return self.is_escalation or not self.next_ids


@dataclass(frozen=True)
class TreeIssue:
    """node_id = None — проблема дерева целиком (нет корня, нет эскалации)."""

    problem: TreeProblem
    node_id: int | None = None


def _reachable(start: Iterable[int], edges: Mapping[int, Sequence[int]]) -> set[int]:
    seen: set[int] = set()
    queue = deque(start)
    while queue:
        node_id = queue.popleft()
        if node_id in seen:
            continue
        seen.add(node_id)
        queue.extend(edges.get(node_id, ()))
    return seen


def validate_tree(nodes: Sequence[TreeNode]) -> list[TreeIssue]:
    """Проблемы дерева по порядку: корень, ссылки, достижимость, тупики, эскалация.

    Пустой список — дерево валидно. У каждого узла — не больше одной проблемы каждого вида.
    Тупики считаются по существующим ссылкам: битая ссылка — отдельная проблема.
    """
    if not nodes:
        return [TreeIssue(TreeProblem.NO_ROOT)]
    by_id = {n.id: n for n in nodes}
    issues: list[TreeIssue] = []

    roots = [n.id for n in nodes if n.is_root]
    if not roots:
        issues.append(TreeIssue(TreeProblem.NO_ROOT))
    elif len(roots) > 1:
        issues.extend(TreeIssue(TreeProblem.MULTIPLE_ROOTS, r) for r in roots)

    edges: dict[int, list[int]] = {}
    reverse: dict[int, list[int]] = {}
    for node in nodes:
        valid = [t for t in node.next_ids if t in by_id]
        if len(valid) < len(node.next_ids):
            issues.append(TreeIssue(TreeProblem.BROKEN_REFERENCE, node.id))
        edges[node.id] = valid
        for target in valid:
            reverse.setdefault(target, []).append(node.id)

    from_root = _reachable(roots, edges)
    if roots:
        issues.extend(
            TreeIssue(TreeProblem.UNREACHABLE, n.id) for n in nodes if n.id not in from_root
        )

    # Узлы, из которых достижим финал, — обратный обход от финалов.
    leads_to_final = _reachable((n.id for n in nodes if n.is_final), reverse)
    issues.extend(
        TreeIssue(TreeProblem.DEAD_END, n.id) for n in nodes if n.id not in leads_to_final
    )

    if roots and not any(by_id[i].is_escalation for i in from_root):
        issues.append(TreeIssue(TreeProblem.NO_ESCALATION))
    return issues
