"""Проверка дерева решений на тупики — чистая функция (Глава 14, ADR 0018 п. 3–4)."""

import random

import pytest

from app.domain.knowledge.tree import TreeIssue, TreeNode, TreeProblem, validate_tree

P = TreeProblem


def node(node_id: int, *next_ids: int, root: bool = False, esc: bool = False) -> TreeNode:
    return TreeNode(node_id, tuple(next_ids), is_root=root, is_escalation=esc)


def problems(nodes: list[TreeNode]) -> set[tuple[TreeProblem, int | None]]:
    return {(i.problem, i.node_id) for i in validate_tree(nodes)}


def test_minimal_valid_tree():
    """Вопрос → решение / эскалация — валидно."""
    assert validate_tree([node(1, 2, 3, root=True), node(2), node(3, esc=True)]) == []


def test_escalation_root_alone_is_valid():
    """Корень-эскалация без вариантов: сразу «Создать обращение» — финал, тупика нет."""
    assert validate_tree([node(1, root=True, esc=True)]) == []


def test_escalation_with_options_is_final():
    """У эскалации могут быть варианты («попробовать ещё раз») — она всё равно финал."""
    nodes = [node(1, 2, root=True), node(2, 1, esc=True)]
    assert validate_tree(nodes) == []


def test_empty_tree_has_no_root():
    assert validate_tree([]) == [TreeIssue(P.NO_ROOT)]


def test_no_root():
    nodes = [node(1, 2), node(2, esc=True)]
    assert problems(nodes) == {(P.NO_ROOT, None)}


def test_multiple_roots_each_reported():
    nodes = [node(1, 3, root=True), node(2, 3, root=True), node(3, esc=True)]
    assert problems(nodes) == {(P.MULTIPLE_ROOTS, 1), (P.MULTIPLE_ROOTS, 2)}


def test_broken_reference():
    nodes = [node(1, 2, 99, root=True), node(2, esc=True)]
    assert problems(nodes) == {(P.BROKEN_REFERENCE, 1)}


def test_broken_reference_only_target_is_dead_end():
    """Единственный вариант ведёт в никуда — и битая ссылка, и тупик (финала не достичь)."""
    nodes = [node(1, 2, 3, root=True), node(2, 99), node(3, esc=True)]
    assert problems(nodes) == {(P.BROKEN_REFERENCE, 2), (P.DEAD_END, 2)}


def test_unreachable_node():
    nodes = [node(1, 2, root=True), node(2, esc=True), node(3, 2)]
    assert problems(nodes) == {(P.UNREACHABLE, 3)}


def test_closed_cycle_is_dead_end():
    """Цикл вопросов без выхода: клиент ходит по кругу — тупик у каждого узла цикла."""
    nodes = [node(1, 2, 4, root=True), node(2, 3), node(3, 2), node(4, esc=True)]
    assert problems(nodes) == {(P.DEAD_END, 2), (P.DEAD_END, 3)}


def test_cycle_with_exit_is_not_dead_end():
    """«Повторите шаг» — цикл допустим, если из него можно выйти к финалу."""
    nodes = [node(1, 2, root=True), node(2, 1, 3), node(3, esc=True)]
    assert validate_tree(nodes) == []


def test_self_loop_without_exit_is_dead_end():
    nodes = [node(1, 2, 3, root=True), node(2, 2), node(3, esc=True)]
    assert problems(nodes) == {(P.DEAD_END, 2)}


def test_root_cycle_without_finals():
    """Корень в цикле, финалов нет: тупики и нет эскалации."""
    nodes = [node(1, 2, root=True), node(2, 1)]
    assert problems(nodes) == {(P.DEAD_END, 1), (P.DEAD_END, 2), (P.NO_ESCALATION, None)}


def test_no_escalation_reachable():
    """Только решения — клиент не сможет создать тикет (C-07)."""
    nodes = [node(1, 2, 3, root=True), node(2), node(3)]
    assert problems(nodes) == {(P.NO_ESCALATION, None)}


def test_unreachable_escalation_does_not_count():
    nodes = [node(1, 2, root=True), node(2), node(3, esc=True)]
    assert problems(nodes) == {(P.UNREACHABLE, 3), (P.NO_ESCALATION, None)}


def test_escalation_check_skipped_without_root():
    """Без корня достижимость не определена: только NO_ROOT, без NO_ESCALATION и UNREACHABLE."""
    nodes = [node(1, 2), node(2)]
    assert problems(nodes) == {(P.NO_ROOT, None)}


def test_issue_order_is_stable():
    nodes = [node(1, 2, root=True), node(2, 2, 99), node(3)]
    assert [(i.problem, i.node_id) for i in validate_tree(nodes)] == [
        (P.BROKEN_REFERENCE, 2),
        (P.UNREACHABLE, 3),
        (P.DEAD_END, 1),  # единственный путь из корня — в цикл без финала
        (P.DEAD_END, 2),
        (P.NO_ESCALATION, None),
    ]


@pytest.mark.parametrize("size", [1, 10, 100])
def test_long_chain_is_valid(size):
    """Цепочка вопросов до эскалации: обход без рекурсии, размер дерева до предела."""
    nodes = [node(i, i + 1, root=i == 1) for i in range(1, size)]
    nodes.append(node(size, root=size == 1, esc=True))
    assert validate_tree(nodes) == []


def _brute_dead_ends(nodes: list[TreeNode]) -> set[int]:
    """Эталон: поиск в глубину из каждого узла отдельно — медленно, но очевидно верно."""
    by_id = {n.id: n for n in nodes}

    def reaches_final(start: int) -> bool:
        seen, stack = set(), [start]
        while stack:
            current = by_id[stack.pop()]
            if current.is_final:
                return True
            if current.id in seen:
                continue
            seen.add(current.id)
            stack.extend(t for t in current.next_ids if t in by_id)
        return False

    return {n.id for n in nodes if not reaches_final(n.id)}


@pytest.mark.parametrize("seed", range(300))
def test_dead_ends_match_brute_force(seed):
    """Случайные графы до 8 узлов (циклы, петли, битые ссылки) — тупики совпадают с эталоном."""
    rnd = random.Random(seed)
    size = rnd.randint(1, 8)
    nodes = [
        TreeNode(
            i,
            tuple(rnd.randint(1, size + 1) for _ in range(rnd.choice([0, 1, 1, 2, 3]))),
            is_root=i == 1,
            is_escalation=rnd.random() < 0.15,
        )
        for i in range(1, size + 1)
    ]
    dead = {i.node_id for i in validate_tree(nodes) if i.problem is P.DEAD_END}
    assert dead == _brute_dead_ends(nodes)
