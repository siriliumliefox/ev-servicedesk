// Коды ошибок контракта → тексты UI (ADR 0025 п. 6): у каждого кода, который называют операции
// кабинета инженера и админ-панели в docs/openapi.yaml, есть русский текст. Новый код в контракте без
// текста — падение.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { parse } from "yaml";
import { ERROR_TEXTS, apiErrorFromResponse, errorText } from "./errors.ts";
import { ApiError } from "./repository.ts";

/** Операции, которые вызывает кабинет инженера (`HttpEngineerRepository`, `ApiSession`). */
const ENGINEER_OPERATIONS = [
  "staffLogin",
  "refreshToken",
  "logout",
  "getCurrentUser",
  "searchVehicleModels",
  "listAggregateTypes",
  "listKnowledgeArticles",
  "listTickets",
  "getTicket",
  "claimTicket",
  "updateTicketStatus",
  "listTicketMessages",
  "createTicketMessage",
  "listMaintenanceRecords",
];

/** Операции админ-панели (`HttpAdminRepository`, глава 22, ADR 0026 п. 2). */
const ADMIN_OPERATIONS = [
  "createAggregateType",
  "listMaintenanceRegulations",
  "reviseMaintenanceRegulation",
  "archiveMaintenanceRegulation",
  "getAggregateStatusThresholds",
  "updateAggregateStatusThresholds",
  "getKnowledgeArticle",
  "createKnowledgeArticle",
  "updateKnowledgeArticle",
  "unpublishKnowledgeArticle",
  "listKnowledgeArticleRevisions",
  "getKnowledgeArticleRevision",
  "listDecisionTreeNodes",
  "createDecisionTreeNode",
  "updateDecisionTreeNode",
  "deleteDecisionTreeNode",
  "validateDecisionTree",
  "createNotification",
  "previewNotificationAudience",
  "listPublishedNotifications",
  "listFirmwareReleases",
  "createFirmwareRelease",
  "listUsers",
  "getUser",
  "createStaffUser",
  "updateUser",
  "resetUserPassword",
  "assignTicket",
  "getTicketResolutionStats",
  "listProblemModels",
  "getMaintenanceConversionStats",
];

const OPERATIONS = [...ENGINEER_OPERATIONS, ...ADMIN_OPERATIONS];

/** Проблемы дерева решений в ответе проверки — не коды ошибок (подписи — в редакторе дерева). */
const TREE_PROBLEMS = ["NO_ROOT", "MULTIPLE_ROOTS", "BROKEN_REFERENCE", "DEAD_END", "UNREACHABLE", "NO_ESCALATION"];

type Operation = { operationId?: string; description?: string; responses?: Record<string, unknown> };

const spec = parse(readFileSync(new URL("../../../docs/openapi.yaml", import.meta.url), "utf8")) as {
  paths: Record<string, Record<string, Operation>>;
};

const operations = Object.values(spec.paths).flatMap((methods) => Object.values(methods));

describe("тексты ошибок", () => {
  it("операции кабинета и админ-панели найдены в контракте", () => {
    const ids = operations.map((op) => op.operationId);
    expect(OPERATIONS.filter((id) => !ids.includes(id))).toEqual([]);
  });

  it("у каждого кода из описаний операций кабинета и админ-панели есть текст", () => {
    const codes = new Set<string>();
    for (const op of operations.filter((o) => OPERATIONS.includes(o.operationId ?? ""))) {
      for (const code of (op.description ?? "").match(/\b[A-Z]+(?:_[A-Z]+)+\b/g) ?? []) {
        if (!TREE_PROBLEMS.includes(code)) codes.add(code);
      }
    }
    expect(codes.size).toBeGreaterThan(3);
    expect([...codes].filter((code) => !(code in ERROR_TEXTS))).toEqual([]);
  });

  it("ответ сервера → текст по коду, не message сервера", () => {
    const response = new Response(null, { status: 409, headers: { "Retry-After": "7" } });
    const e = apiErrorFromResponse(response, { error: { code: "TICKET_RESOLVED", message: "internal" } });
    expect([e.code, e.message, e.retryAfter]).toEqual(["TICKET_RESOLVED", ERROR_TEXTS.TICKET_RESOLVED, 7]);
    expect(errorText(e)).toBe(ERROR_TEXTS.TICKET_RESOLVED);
    expect(apiErrorFromResponse(new Response(null, { status: 502 }), null).code).toBe("INTERNAL_ERROR");
    expect(errorText(new ApiError("NEW_CODE", "", 409))).toBe("Что-то пошло не так. Повторите попытку.");
  });
});
