// Правила дерева решений в прототипе — как backend (ADR 0018 п. 3–4, ADR 0026 п. 9): чистые функции над
// шагами одной статьи. Сохранение шага отклоняет второй корень и переход не в это дерево (`checkNode`), проверка
// дерева целиком находит тупики, недостижимые шаги и отсутствие эскалации (`validateTree`).
import type { DecisionTreeNode, DecisionTreeNodeCreateRequest, DecisionTreeValidationResult } from "../data/models.ts";
import { ApiError } from "../data/repository.ts";

/** Как backend (`_check_node`): корень единственный (409), переходы — только на шаги этой статьи (422). */
export function checkNode(siblings: DecisionTreeNode[], body: DecisionTreeNodeCreateRequest, nodeId: number | null): void {
  if (body.is_root && siblings.some((n) => n.is_root && n.id !== nodeId)) {
    throw new ApiError("DECISION_TREE_ROOT_EXISTS", "У дерева уже есть корень", 409, "is_root");
  }
  const known = new Set(siblings.map((n) => n.id));
  if ((body.options ?? []).some((o) => o.next_node_id == null || !known.has(o.next_node_id))) {
    throw new ApiError("INVALID_NEXT_NODE", "Вариант ведёт к шагу не из этого дерева", 422, "options");
  }
}

/** Шаги, достижимые из `start` по `next` (обход в ширину). */
function reach(start: number[], next: (id: number) => number[]): Set<number> {
  const seen = new Set<number>();
  const queue = [...start];
  while (queue.length) {
    const id = queue.shift()!;
    if (seen.has(id)) continue;
    seen.add(id);
    queue.push(...next(id));
  }
  return seen;
}

/**
 * Проверка дерева целиком: финал — эскалация или шаг без вариантов; тупик — шаг, из которого финал недостижим
 * (в т. ч. цикл).
 */
export function validateTree(nodes: DecisionTreeNode[]): DecisionTreeValidationResult {
  if (nodes.length === 0) return { is_valid: false, issues: [{ problem: "NO_ROOT" }] };
  const ids = new Set(nodes.map((n) => n.id));
  const issues: DecisionTreeValidationResult["issues"] = [];
  const roots = nodes.filter((n) => n.is_root);
  if (roots.length === 0) issues.push({ problem: "NO_ROOT" });
  if (roots.length > 1) for (const r of roots) issues.push({ node_id: r.id, problem: "MULTIPLE_ROOTS" });
  const edges = new Map<number, number[]>();
  for (const n of nodes) {
    const targets = (n.options ?? []).map((o) => o.next_node_id).filter((t): t is number => t !== null);
    if (targets.some((t) => !ids.has(t))) issues.push({ node_id: n.id, problem: "BROKEN_REFERENCE" });
    edges.set(n.id, targets.filter((t) => ids.has(t)));
  }
  const fromRoot = reach(roots.map((r) => r.id), (id) => edges.get(id) ?? []);
  if (roots.length) for (const n of nodes) if (!fromRoot.has(n.id)) issues.push({ node_id: n.id, problem: "UNREACHABLE" });
  const isFinal = (n: DecisionTreeNode) => n.is_escalation || (n.options ?? []).length === 0;
  const incoming = (id: number) => nodes.filter((n) => edges.get(n.id)!.includes(id)).map((n) => n.id);
  const leadsToFinal = reach(nodes.filter(isFinal).map((n) => n.id), incoming);
  for (const n of nodes) if (!leadsToFinal.has(n.id)) issues.push({ node_id: n.id, problem: "DEAD_END" });
  if (roots.length && !nodes.some((n) => n.is_escalation && fromRoot.has(n.id))) issues.push({ problem: "NO_ESCALATION" });
  return { is_valid: issues.length === 0, issues };
}
