// Репозиторий прототипа (Глава 8, ADR 0012): операции OpenAPI v1 на фикстурах в памяти, без сети и Docker.
// Ошибки — в формате контракта (`ApiError`: code + HTTP-статус). Правила, которые в продукте проверяет
// backend (переходы статусов тикета, claim 409, валидация дерева решений, пользователи), здесь —
// упрощённо, с теми же кодами ошибок; финальные правила — backend (главы 12–17, 22).
import type {
  AggregateReplaceRequest,
  AggregateStatus,
  AggregateStatusThresholds,
  AggregateStatusThresholdsUpdateRequest,
  AggregateType,
  AggregateTypeCreateRequest,
  DateRange,
  DecisionTreeNode,
  DecisionTreeNodeCreateRequest,
  DecisionTreeValidationResult,
  FirmwareRelease,
  FirmwareReleaseCreateRequest,
  KnowledgeArticle,
  KnowledgeArticleCreateRequest,
  KnowledgeArticleList,
  KnowledgeArticleRevision,
  KnowledgeArticleRevisionSummary,
  KnowledgeArticleUpdateRequest,
  MaintenanceConversionStats,
  MaintenanceRecord,
  MaintenanceRecordCreateRequest,
  MaintenanceRecordList,
  MaintenanceRegulation,
  MaintenanceRegulationCreateRequest,
  Notification,
  NotificationAudiencePreview,
  NotificationCreateRequest,
  ProblemModelStats,
  PublishedNotificationList,
  StaffUserCreateRequest,
  Ticket,
  TicketCategory,
  TicketDetail,
  TicketList,
  TicketMessage,
  TicketResolutionStats,
  TicketStatus,
  UserList,
  UserPublic,
  UserUpdateRequest,
  Vehicle,
  VehicleModel,
} from "../data/models.ts";
import { TICKET_CATEGORIES } from "../data/models.ts";
import { toIsoDate } from "../data/format.ts";
import { allowedTransitions } from "../data/ticketFlow.ts";
import { checkNode, validateTree } from "./decisionTree.ts";
import {
  ApiError,
  type AdminRepository,
  type AnalyticsQuery,
  type EngineerRepository,
  type ListArticlesQuery,
  type ListPublishedQuery,
  type ListTicketsQuery,
  type ListUsersQuery,
  type PageQuery,
  type TicketLiveHandlers,
} from "../data/repository.ts";
import {
  ADMIN_ID,
  AGGREGATE_STATUSES,
  AGGREGATE_TYPES,
  ARTICLES,
  DECISION_TREE_NODES,
  ENGINEER_ID,
  FIRMWARE_RELEASES,
  MAINTENANCE_RECORDS,
  USERS,
  VEHICLE_MODELS,
  VEHICLES,
  seedNotifications,
  seedRegulations,
  seedTickets,
  type TicketRecord,
} from "./fixtures.ts";

/** Сценарии ревью (панель «Демо»): данные по умолчанию или пустая система. */
export type PrototypeScenario = "demo" | "empty";

export interface PrototypeOptions {
  /** Чей кабинет: инженер (#7) или администратор (#1). */
  role: "engineer" | "admin";
  /** Часы прототипа; в тестах — фиксированное время. */
  now?: () => Date;
  /** Искусственная задержка ответа, мс (показывает состояния загрузки). В тестах — 0. */
  latencyMs?: number;
  scenario?: PrototypeScenario;
}

/** `Ticket.summary` — первые 140 символов описания (OpenAPI 1.4.0, ADR 0017). */
const SUMMARY_LENGTH = 140;

const clone = <T>(value: T): T => structuredClone(value);
// Витрина аналитики обновляется раз в 5 минут (ADR 0020 п. 2); доли — до 0,0001, как в API.
const ANALYTICS_LAG_MS = 3 * 60_000;
const round4 = (value: number) => Math.round(value * 10_000) / 10_000;

/** Страница выборки, как `PaginationMeta` контракта (page с 1, page_size по умолчанию 20). */
const slice = <T>(items: T[], query: PageQuery) => {
  const size = query.page_size ?? 20;
  const number = query.page ?? 1;
  return {
    items: items.slice((number - 1) * size, number * size),
    meta: { page: number, page_size: size, total_items: items.length, total_pages: Math.ceil(items.length / size) },
  };
};

const validation = (message: string, field?: string) => new ApiError("VALIDATION_ERROR", message, 422, field);

export class PrototypeRepository implements EngineerRepository, AdminRepository {
  readonly role: "engineer" | "admin";
  private readonly clock: () => Date;
  private readonly latencyMs: number;
  private offline = false;
  private scenario: PrototypeScenario;

  private tickets: TicketRecord[] = [];
  private readonly watchers = new Map<number, Set<TicketLiveHandlers>>();
  private articles: KnowledgeArticle[] = [];
  private treeNodes: DecisionTreeNode[] = [];
  private aggregateTypes: AggregateType[] = [];
  private regulations: MaintenanceRegulation[] = [];
  private statuses: Record<number, AggregateStatus[]> = {};
  private records: Record<number, MaintenanceRecord[]> = {};
  private vehicles: Vehicle[] = [];
  private thresholds: AggregateStatusThresholds = {
    yellow_from_percent: 70,
    red_above_percent: 100,
    updated_at: "",
    reminder_before_km: 1000,
    reminder_before_days: 14,
  };
  private firmware: FirmwareRelease[] = [];
  private notifications: Notification[] = [];
  private users: UserPublic[] = [];
  private revisions: KnowledgeArticleRevision[] = [];
  private nextId = 10_000;

  constructor(options: PrototypeOptions) {
    this.role = options.role;
    this.clock = options.now ?? (() => new Date());
    this.latencyMs = options.latencyMs ?? 0;
    this.scenario = options.scenario ?? "demo";
    this.reset();
  }

  // ---------- Управление прототипом (панель «Демо»; в HTTP-реализации нет) ----------

  now(): Date {
    return this.clock();
  }

  isOffline(): boolean {
    return this.offline;
  }

  setOffline(value: boolean): void {
    this.offline = value;
  }

  getScenario(): PrototypeScenario {
    return this.scenario;
  }

  setScenario(value: PrototypeScenario): void {
    this.scenario = value;
    this.reset();
  }

  /** Сбросить данные к фикстурам выбранного сценария. */
  reset(): void {
    const now = this.clock();
    const empty = this.scenario === "empty";
    this.tickets = empty ? [] : seedTickets(now);
    this.articles = empty ? [] : clone(ARTICLES);
    this.treeNodes = empty ? [] : clone(DECISION_TREE_NODES);
    this.aggregateTypes = clone(AGGREGATE_TYPES);
    this.regulations = empty ? [] : seedRegulations();
    this.statuses = clone(AGGREGATE_STATUSES);
    this.records = clone(MAINTENANCE_RECORDS);
    // Пробег меняет работа по агрегату — у каждого экземпляра свои авто.
    this.vehicles = VEHICLES.map((v) => clone(v.vehicle));
    this.thresholds = {
      yellow_from_percent: 70,
      red_above_percent: 100,
      updated_at: "2026-10-01T08:00:00Z",
      reminder_before_km: 1000,
      reminder_before_days: 14,
    };
    this.firmware = empty ? [] : clone(FIRMWARE_RELEASES);
    this.notifications = empty ? [] : seedNotifications(now);
    this.users = Object.values(clone(USERS));
    // Версия — снимок опубликованной редакции (ADR 0018 п. 1); у фикстур — только текущая.
    this.revisions = this.articles.filter((a) => a.is_published).map((a) => this.snapshot(a, a.updated_at));
  }

  // ---------- Общие ----------

  getCurrentUser(): Promise<UserPublic> {
    return this.call(() => this.user(this.role === "admin" ? ADMIN_ID : ENGINEER_ID));
  }

  searchVehicleModels(): Promise<VehicleModel[]> {
    return this.call(() => VEHICLE_MODELS);
  }

  listAggregateTypes(): Promise<AggregateType[]> {
    return this.call(() => this.aggregateTypes);
  }

  listKnowledgeArticles(query: ListArticlesQuery = {}): Promise<KnowledgeArticleList> {
    return this.call(() => {
      const needle = query.search?.trim().toLocaleLowerCase("ru");
      const items = this.articles.filter(
        (a) =>
          (query.article_type === undefined || a.article_type === query.article_type) &&
          (query.is_published === undefined || a.is_published === query.is_published) &&
          (query.vehicle_model_id === undefined || a.vehicle_model_id === null || a.vehicle_model_id === query.vehicle_model_id) &&
          (!needle || `${a.title}\n${a.content}`.toLocaleLowerCase("ru").includes(needle)),
      );
      return slice(items, query);
    });
  }

  // ---------- Инженер: тикеты ----------

  listTickets(query: ListTicketsQuery = {}): Promise<TicketList> {
    return this.call(() => {
      const since = query.resolved_since === undefined ? null : Date.parse(query.resolved_since);
      const items = this.tickets
        .map((t) => this.toTicket(t))
        .filter(
          (t) =>
            (query.status === undefined || t.status === query.status) &&
            (query.category === undefined || t.category === query.category) &&
            (query.assigned_engineer_id === undefined || t.assigned_engineer_id === query.assigned_engineer_id) &&
            (query.overdue === undefined || t.is_overdue === query.overdue) &&
            (since === null || (t.resolved_at != null && Date.parse(t.resolved_at) >= since)),
        )
        // Персонал — по сроку SLA (как backend, ADR 0017 п. 3).
        .sort((a, b) => a.sla_due_at.localeCompare(b.sla_due_at) || a.id - b.id);
      return slice(items, query);
    });
  }

  getTicket(ticketId: number): Promise<TicketDetail> {
    return this.call(() => this.toDetail(this.ticket(ticketId)));
  }

  claimTicket(ticketId: number): Promise<TicketDetail> {
    return this.call(() => {
      const t = this.ticket(ticketId);
      if (t.assigned_engineer_id !== null && t.assigned_engineer_id !== ENGINEER_ID) {
        throw new ApiError("TICKET_ALREADY_CLAIMED", "Тикет уже взял в работу другой инженер", 409);
      }
      t.assigned_engineer_id = ENGINEER_ID;
      if (t.status === "new") t.status = "in_progress";
      this.emitTicket(t);
      return this.toDetail(t);
    });
  }

  /** Админ: назначить активного инженера или вернуть тикет в очередь (null), как assignTicket. */
  assignTicket(ticketId: number, engineerId: number | null): Promise<TicketDetail> {
    return this.call(() => {
      const t = this.ticket(ticketId);
      if (t.status === "resolved") throw new ApiError("TICKET_RESOLVED", "Тикет решён", 409);
      if (engineerId !== null) {
        const engineer = this.users.find((u) => u.id === engineerId);
        if (!engineer || engineer.role !== "engineer" || !engineer.is_active) {
          throw new ApiError("ASSIGNEE_NOT_ENGINEER", "Назначить можно только активного инженера", 422, "assigned_engineer_id");
        }
        if (t.status === "new") t.status = "in_progress";
      } else {
        t.status = "new";
      }
      t.assigned_engineer_id = engineerId;
      this.emitTicket(t);
      return this.toDetail(t);
    });
  }

  updateTicketStatus(ticketId: number, status: TicketStatus): Promise<TicketDetail> {
    return this.call(() => {
      const t = this.ticket(ticketId);
      if (this.role === "engineer" && t.assigned_engineer_id !== ENGINEER_ID) {
        throw new ApiError("FORBIDDEN", "Статус меняет инженер, назначенный на тикет", 403);
      }
      if (t.status !== status && !allowedTransitions(t.status).includes(status)) {
        throw new ApiError("INVALID_STATUS_TRANSITION", "Такой переход статуса недоступен", 409);
      }
      if (t.status !== status) {
        t.status = status;
        t.resolved_at = status === "resolved" ? this.clock().toISOString() : null;
        this.emitTicket(t);
      }
      return this.toDetail(t);
    });
  }

  listTicketMessages(ticketId: number, query: { after_id?: number } = {}): Promise<TicketMessage[]> {
    return this.call(() => this.ticket(ticketId).messages.filter((m) => m.id > (query.after_id ?? 0)));
  }

  createTicketMessage(ticketId: number, body: string): Promise<TicketMessage> {
    return this.call(() => {
      const t = this.ticket(ticketId);
      if (this.role === "engineer" && t.assigned_engineer_id !== ENGINEER_ID) {
        throw new ApiError("FORBIDDEN", "Писать в чат может инженер, назначенный на тикет", 403);
      }
      if (t.status === "resolved") throw new ApiError("TICKET_RESOLVED", "Тикет решён", 409);
      if (!body.trim()) throw validation("Сообщение пустое", "body");
      const message: TicketMessage = {
        id: this.nextId++,
        author: USERS[this.role === "admin" ? ADMIN_ID : ENGINEER_ID],
        body: body.trim(),
        attachments: [],
        created_at: this.clock().toISOString(),
      };
      t.messages.push(message);
      this.emit(ticketId, (h) => h.onMessage(clone(message)));
      return message;
    });
  }

  listMaintenanceRecords(vehicleId: number, query: PageQuery = {}): Promise<MaintenanceRecordList> {
    return this.call(() => slice(this.records[vehicleId] ?? [], query));
  }

  replaceAggregateStatus(vehicleId: number, aggregateTypeCode: string, body: AggregateReplaceRequest): Promise<AggregateStatus> {
    return this.call(() => {
      const vehicle = this.vehicleForChange(vehicleId);
      const current = (this.statuses[vehicleId] ?? []).find((s) => s.aggregate_type_code === aggregateTypeCode);
      if (!current) throw new ApiError("AGGREGATE_TYPE_NOT_FOUND", "Неизвестный код агрегата", 404);
      if (body.replaced_at > toIsoDate(this.clock())) throw validation("Дата замены не может быть позже сегодняшней.", "replaced_at");
      if (body.mileage_at_replacement > vehicle.mileage) {
        throw new ApiError("MILEAGE_AHEAD_OF_VEHICLE", "Пробег замены больше текущего пробега авто — уточните пробег у клиента.", 409);
      }
      this.addRecord(vehicleId, aggregateTypeCode, body.replaced_at, body.mileage_at_replacement, body.description ?? null, "replacement");
      // Замена задним числом попадает только в историю ТО (ADR 0016) — счётчик не сбрасывается.
      if (current.last_replaced_at && body.replaced_at < current.last_replaced_at) return clone(current);
      // В прототипе нет регламентов авто — свежая замена всегда 🟢 с нулевой выработкой.
      Object.assign(current, {
        status: "green",
        percentage: 0,
        last_replaced_at: body.replaced_at,
        last_replaced_mileage: body.mileage_at_replacement,
      });
      return clone(current);
    });
  }

  createMaintenanceRecord(vehicleId: number, body: MaintenanceRecordCreateRequest): Promise<MaintenanceRecord> {
    return this.call(() => {
      const vehicle = this.vehicleForChange(vehicleId);
      const code = body.aggregate_type_code ?? null;
      const description = body.description?.trim() || null;
      if (body.performed_at > toIsoDate(this.clock())) throw validation("Дата работы не может быть позже сегодняшней.", "performed_at");
      if (code === null && description === null) throw validation("Опишите работу: без агрегата нужен комментарий.", "description");
      // Пробег работы выше текущего поднимает пробег авто (контракт createMaintenanceRecord).
      vehicle.mileage = Math.max(vehicle.mileage, body.mileage_at_service);
      return clone(this.addRecord(vehicleId, code, body.performed_at, body.mileage_at_service, description, "work"));
    });
  }

  /** События — от действий в этой сессии прототипа (сети нет): «живой» чат без WebSocket. */
  watchTicket(ticketId: number, handlers: TicketLiveHandlers): () => void {
    const set = this.watchers.get(ticketId) ?? new Set<TicketLiveHandlers>();
    set.add(handlers);
    this.watchers.set(ticketId, set);
    queueMicrotask(() => {
      if (!set.has(handlers)) return;
      handlers.onState?.("live");
      handlers.onReady();
    });
    return () => set.delete(handlers);
  }

  // ---------- Админ: справочник агрегатов, регламенты, пороги ----------

  createAggregateType(body: AggregateTypeCreateRequest): Promise<AggregateType> {
    return this.call(() => {
      if (!/^[a-z][a-z0-9_]{1,49}$/.test(body.code)) {
        throw validation("Код — латиница в нижнем регистре, цифры и «_», от 2 символов", "code");
      }
      if (!body.name.trim()) throw validation("Укажите название", "name");
      if (this.aggregateTypes.some((a) => a.code === body.code)) {
        throw new ApiError("CONFLICT", "Агрегат с таким кодом уже есть", 409);
      }
      const created = { code: body.code, name: body.name.trim() };
      this.aggregateTypes.push(created);
      return created;
    });
  }

  listMaintenanceRegulations(query: { vehicle_model_id?: number; include_archived?: boolean }): Promise<MaintenanceRegulation[]> {
    return this.call(() =>
      this.regulations.filter(
        (r) =>
          (query.vehicle_model_id === undefined || r.vehicle_model_id === query.vehicle_model_id) &&
          (query.include_archived || !r.is_archived),
      ),
    );
  }

  reviseMaintenanceRegulation(body: MaintenanceRegulationCreateRequest): Promise<MaintenanceRegulation> {
    return this.call(() => {
      const km = body.interval_km ?? null;
      const months = body.interval_months ?? null;
      if (km === null && months === null) throw validation("Укажите интервал в км и/или месяцах", "interval_km");
      if (km !== null && (!Number.isInteger(km) || km < 1)) throw validation("Интервал в км — целое число ≥ 1", "interval_km");
      if (months !== null && (!Number.isInteger(months) || months < 1)) {
        throw validation("Интервал в месяцах — целое число ≥ 1", "interval_months");
      }
      // Пересмотр, а не PATCH: активная версия архивируется, создаётся новая (reviseMaintenanceRegulation).
      for (const r of this.regulations) {
        if (r.vehicle_model_id === body.vehicle_model_id && r.aggregate_type_code === body.aggregate_type_code) {
          r.is_archived = true;
        }
      }
      const created: MaintenanceRegulation = {
        id: this.nextId++,
        vehicle_model_id: body.vehicle_model_id,
        aggregate_type_code: body.aggregate_type_code,
        interval_km: km,
        interval_months: months,
        is_archived: false,
      };
      this.regulations.push(created);
      return created;
    });
  }

  archiveMaintenanceRegulation(regulationId: number): Promise<void> {
    return this.call(() => {
      const r = this.regulations.find((x) => x.id === regulationId);
      if (!r) throw new ApiError("NOT_FOUND", "Регламент не найден", 404);
      r.is_archived = true;
    });
  }

  getAggregateStatusThresholds(): Promise<AggregateStatusThresholds> {
    return this.call(() => this.thresholds);
  }

  updateAggregateStatusThresholds(body: AggregateStatusThresholdsUpdateRequest): Promise<AggregateStatusThresholds> {
    return this.call(() => {
      const { yellow_from_percent: y, red_above_percent: r } = body;
      if (!Number.isInteger(y) || !Number.isInteger(r) || y < 1 || r > 200 || y >= r) {
        throw validation("Нужно 1 ≤ «жёлтый с» < «красный выше» ≤ 200", "yellow_from_percent");
      }
      // Порог напоминания о ТО (ADR 0019 п. 5): не передан — не меняется.
      const km = body.reminder_before_km ?? this.thresholds.reminder_before_km;
      const days = body.reminder_before_days ?? this.thresholds.reminder_before_days;
      if (!Number.isInteger(km) || !Number.isInteger(days) || km < 1 || km > 100000 || days < 1 || days > 365) {
        throw validation("Напоминание о ТО: 1–100 000 км и 1–365 дней", "reminder_before_km");
      }
      this.thresholds = {
        yellow_from_percent: y,
        red_above_percent: r,
        updated_at: this.clock().toISOString(),
        reminder_before_km: km,
        reminder_before_days: days,
      };
      return this.thresholds;
    });
  }

  // ---------- Админ: база знаний ----------

  getKnowledgeArticle(articleId: number): Promise<KnowledgeArticle> {
    return this.call(() => this.article(articleId));
  }

  createKnowledgeArticle(body: KnowledgeArticleCreateRequest): Promise<KnowledgeArticle> {
    return this.call(() => {
      this.checkArticle(body.title, body.content);
      if (body.firmware_release_id != null) {
        const fw = this.firmware.find((f) => f.id === body.firmware_release_id);
        if (!fw || fw.vehicle_model_id !== body.vehicle_model_id) {
          throw validation("Прошивка должна относиться к выбранной модели", "firmware_release_id");
        }
      }
      const category = body.category ?? null;
      if (body.article_type === "troubleshooting" && category === null) {
        throw validation("Выберите категорию ошибки", "category");
      }
      const created: KnowledgeArticle = {
        id: this.nextId++,
        article_type: body.article_type,
        category,
        title: body.title.trim(),
        content: body.content,
        vehicle_model_id: body.vehicle_model_id ?? null,
        firmware_release_id: body.firmware_release_id ?? null,
        version: 1,
        is_published: false,
        updated_at: new Date().toISOString(),
      };
      this.articles.unshift(created);
      return created;
    });
  }

  updateKnowledgeArticle(articleId: number, body: KnowledgeArticleUpdateRequest): Promise<KnowledgeArticle> {
    return this.call(() => {
      const a = this.article(articleId);
      const title = body.title ?? a.title;
      const content = body.content ?? a.content ?? "";
      this.checkArticle(title, content);
      if (body.is_published && a.article_type === "troubleshooting") {
        const result = validateTree(this.nodesOf(articleId));
        if (!result.is_valid) {
          throw new ApiError("DECISION_TREE_INVALID", "В дереве решений есть ошибки — исправьте перед публикацией", 409);
        }
      }
      const category = body.category === undefined ? a.category : body.category;
      if (a.article_type === "troubleshooting" && category === null) throw validation("Выберите категорию ошибки", "category");
      // Версия — опубликованная редакция (ADR 0018 п. 1): правка опубликованной статьи — +1,
      // правки черновика версий не создают. Упрощение: снимков и истории версий в прототипе нет.
      const changed = title.trim() !== a.title || content !== a.content || category !== a.category;
      const wasPublished = a.is_published;
      const published = body.is_published ?? a.is_published;
      const known = this.revisions.some((r) => r.article_id === a.id);
      // Новая версия — правка опубликованной или повторная публикация с правками; первая публикация — v1.
      const next = !known ? 1 : (wasPublished || published) && changed ? a.version + 1 : a.version;
      Object.assign(a, {
        title: title.trim(),
        content,
        category,
        is_published: published,
        version: next,
        updated_at: this.clock().toISOString(),
      });
      if (published && !this.revisions.some((r) => r.article_id === a.id && r.version === next)) {
        this.revisions.push(this.snapshot(a, a.updated_at));
      }
      return a;
    });
  }

  listKnowledgeArticleRevisions(articleId: number): Promise<KnowledgeArticleRevisionSummary[]> {
    return this.call(() => {
      this.article(articleId);
      return this.revisions
        .filter((r) => r.article_id === articleId)
        .sort((a, b) => b.version - a.version)
        .map(({ version, title, published_at }) => ({ version, title, published_at }));
    });
  }

  getKnowledgeArticleRevision(articleId: number, version: number): Promise<KnowledgeArticleRevision> {
    return this.call(() => {
      const r = this.revisions.find((x) => x.article_id === articleId && x.version === version);
      if (!r) throw new ApiError("NOT_FOUND", "Версия не найдена", 404);
      return r;
    });
  }

  unpublishKnowledgeArticle(articleId: number): Promise<void> {
    return this.call(() => {
      this.article(articleId).is_published = false;
    });
  }

  listDecisionTreeNodes(articleId: number): Promise<DecisionTreeNode[]> {
    return this.call(() => {
      this.article(articleId);
      return this.nodesOf(articleId);
    });
  }

  createDecisionTreeNode(articleId: number, body: DecisionTreeNodeCreateRequest): Promise<DecisionTreeNode> {
    return this.call(() => {
      this.editableTree(articleId);
      if (!body.question_text.trim()) throw validation("Введите текст шага", "question_text");
      checkNode(this.nodesOf(articleId), body, null);
      const created: DecisionTreeNode = { ...clone(body), id: this.nextId++, article_id: articleId };
      this.treeNodes.push(created);
      return created;
    });
  }

  updateDecisionTreeNode(nodeId: number, body: DecisionTreeNodeCreateRequest): Promise<DecisionTreeNode> {
    return this.call(() => {
      const n = this.treeNodes.find((x) => x.id === nodeId);
      if (!n) throw new ApiError("NOT_FOUND", "Шаг не найден", 404);
      this.editableTree(n.article_id);
      if (!body.question_text.trim()) throw validation("Введите текст шага", "question_text");
      checkNode(this.nodesOf(n.article_id), body, n.id);
      Object.assign(n, clone(body));
      return n;
    });
  }

  deleteDecisionTreeNode(nodeId: number): Promise<void> {
    return this.call(() => {
      const n = this.treeNodes.find((x) => x.id === nodeId);
      if (!n) return;
      this.editableTree(n.article_id);
      if (this.treeNodes.some((x) => (x.options ?? []).some((o) => o.next_node_id === nodeId))) {
        throw new ApiError("DECISION_TREE_NODE_REFERENCED", "На шаг ссылаются варианты других шагов", 409);
      }
      this.treeNodes = this.treeNodes.filter((x) => x.id !== nodeId);
    });
  }

  validateDecisionTree(articleId: number): Promise<DecisionTreeValidationResult> {
    return this.call(() => validateTree(this.nodesOf(articleId)));
  }

  // ---------- Админ: публикации и прошивки ----------

  createNotification(body: NotificationCreateRequest): Promise<Notification> {
    return this.call(() => {
      if (body.type === "maintenance") {
        throw new ApiError("NOTIFICATION_TYPE_RESERVED", "Напоминания о ТО создаёт система", 422, "type");
      }
      if (!body.message.trim()) throw validation("Введите текст уведомления", "message");
      if (body.message.length > 500) throw validation("Не длиннее 500 символов", "message");
      const created: Notification = {
        id: this.nextId++,
        type: body.type,
        target_vehicle_model_id: body.target_vehicle_model_id ?? null,
        firmware_release_id: body.firmware_release_id ?? null,
        message: body.message.trim(),
        created_at: this.clock().toISOString(),
      };
      this.notifications.unshift(created);
      return created;
    });
  }

  /** Аудитория — как backend (ADR 0019): все клиенты или владельцы модели; у прошивки — с более ранней версией. */
  previewNotificationAudience(body: NotificationCreateRequest): Promise<NotificationAudiencePreview> {
    return this.call(() => {
      const recipients = this.audience(body.target_vehicle_model_id ?? null);
      // В прототипе у каждого второго клиента — два устройства.
      return { recipients, devices: recipients + Math.floor(recipients / 2) };
    });
  }

  listPublishedNotifications(query: ListPublishedQuery = {}): Promise<PublishedNotificationList> {
    return this.call(() => {
      const items = this.notifications
        .filter(
          (n) =>
            n.type !== "maintenance" &&
            (query.type === undefined || n.type === query.type) &&
            (query.target_vehicle_model_id === undefined || n.target_vehicle_model_id === query.target_vehicle_model_id),
        )
        .map((n) => {
          const recipients = this.audience(n.target_vehicle_model_id ?? null);
          const delivered = Math.round(recipients * 0.8);
          return {
            ...n,
            stats: {
              recipients,
              delivered,
              failed: recipients - delivered,
              opened: Math.round(delivered * 0.5),
              read: Math.round(recipients * 0.6),
            },
          };
        });
      return slice(items, query);
    });
  }

  listFirmwareReleases(query: { vehicle_model_id?: number } = {}): Promise<FirmwareRelease[]> {
    return this.call(() =>
      this.firmware
        .filter((f) => query.vehicle_model_id === undefined || f.vehicle_model_id === query.vehicle_model_id)
        .sort((a, b) => b.released_at.localeCompare(a.released_at)),
    );
  }

  createFirmwareRelease(body: FirmwareReleaseCreateRequest): Promise<FirmwareRelease> {
    return this.call(() => {
      const version = body.version.trim();
      if (!version || version.length > 50) throw validation("Версия — от 1 до 50 символов", "version");
      if (this.firmware.some((f) => f.vehicle_model_id === body.vehicle_model_id && f.version === version)) {
        throw new ApiError("CONFLICT", "Такая версия для модели уже опубликована", 409);
      }
      const release: FirmwareRelease = { id: this.nextId++, vehicle_model_id: body.vehicle_model_id, version, released_at: body.released_at };
      this.firmware.push(release);
      // Атомарно с релизом — уведомление type=firmware с таргетингом по модели (createFirmwareRelease).
      const model = VEHICLE_MODELS.find((m) => m.id === body.vehicle_model_id)!;
      this.notifications.unshift({
        id: this.nextId++,
        type: "firmware",
        target_vehicle_model_id: body.vehicle_model_id,
        firmware_release_id: release.id,
        message: `Доступна прошивка ${version} для ${model.brand} ${model.model}. Запишитесь на обновление.`,
        created_at: this.clock().toISOString(),
      });
      return release;
    });
  }

  // ---------- Админ: пользователи ----------

  listUsers(query: ListUsersQuery = {}): Promise<UserList> {
    return this.call(() => {
      const needle = query.search?.trim();
      const items = this.users
        .filter(
          (u) =>
            (query.role === undefined || u.role === query.role) &&
            (query.is_active === undefined || u.is_active === query.is_active) &&
            (!needle || (u.phone ?? "").includes(needle)),
        )
        .sort((a, b) => a.id - b.id);
      return slice(items, query);
    });
  }

  getUser(userId: number): Promise<UserPublic> {
    return this.call(() => this.user(userId));
  }

  createStaffUser(body: StaffUserCreateRequest): Promise<UserPublic> {
    return this.call(() => {
      if (!/^\+[1-9]\d{7,14}$/.test(body.phone)) throw validation("Телефон — в формате +375XXXXXXXXX", "phone");
      if (body.password.length < 12 || body.password.length > 128) throw validation("Пароль — от 12 до 128 символов", "password");
      if (this.users.some((u) => u.phone === body.phone)) {
        throw new ApiError("PHONE_ALREADY_REGISTERED", "Телефон уже зарегистрирован", 409);
      }
      const created: UserPublic = {
        id: this.nextId++,
        phone: body.phone,
        role: body.role,
        is_active: true,
        telegram_id: null,
        created_at: this.clock().toISOString(),
      };
      this.users.push(created);
      return created;
    });
  }

  updateUser(userId: number, body: UserUpdateRequest): Promise<UserPublic> {
    return this.call(() => {
      const u = this.user(userId);
      if (body.role != null && body.role !== u.role && u.role === "client") {
        throw new ApiError("ROLE_CHANGE_NOT_ALLOWED", "Смена роли клиента не поддерживается", 409);
      }
      const role = body.role ?? u.role;
      const active = body.is_active ?? u.is_active;
      const admins = this.users.filter((x) => x.role === "admin" && x.is_active);
      if (u.role === "admin" && u.is_active && !(role === "admin" && active) && admins.length === 1) {
        throw new ApiError("LAST_ADMIN", "Нельзя понизить или заблокировать последнего администратора", 409);
      }
      Object.assign(u, { role, is_active: active });
      return u;
    });
  }

  resetUserPassword(userId: number, password: string): Promise<void> {
    return this.call(() => {
      const u = this.user(userId);
      if (u.role === "client") throw new ApiError("PASSWORD_NOT_ALLOWED", "У клиента нет пароля", 409);
      if (password.length < 12 || password.length > 128) throw validation("Пароль — от 12 до 128 символов", "password");
    });
  }

  // ---------- Админ: аналитика ----------
  // В прототипе — детерминированные значения, пропорциональные длине периода (не из тикетов фикстур).
  // computed_at — витрина «обновлена» несколько минут назад (ADR 0020 п. 3).

  getTicketResolutionStats(query: AnalyticsQuery): Promise<TicketResolutionStats> {
    return this.call(() => {
      const { date_from, date_to } = query;
      const range = { date_from, date_to };
      const days = this.days(range) * this.share(query);
      const created = this.scenario === "empty" ? 0 : Math.round(days * 4.3);
      const resolved = Math.round(created * 0.9);
      return {
        ...range,
        tickets_created: created,
        tickets_resolved: resolved,
        tickets_resolved_overdue: Math.round(resolved * 0.12),
        avg_first_response_hours: created ? 0.4 : null,
        avg_resolution_hours: resolved ? 18.6 : null,
        median_resolution_hours: resolved ? 11.2 : null,
        computed_at: this.computedAt(),
      };
    });
  }

  listProblemModels(range: DateRange): Promise<ProblemModelStats[]> {
    return this.call(() => {
      if (this.scenario === "empty") return [];
      const days = this.days(range);
      const shares: [number, number, number[]][] = [
        // модель, авто модели, доли категорий navigation/audio/sim/app_crash/maintenance
        [1, 46, [0.34, 0.08, 0.18, 0.28, 0.12]],
        [3, 21, [0.22, 0.12, 0.3, 0.2, 0.16]],
        [2, 33, [0.1, 0.25, 0.15, 0.3, 0.2]],
      ];
      const volume = [2.1, 1.3, 0.9];
      return shares.map(([modelId, vehicles, parts], i) => {
        const total = Math.max(1, Math.round(days * volume[i]));
        return {
          vehicle_model: VEHICLE_MODELS.find((m) => m.id === modelId)!,
          tickets_total: total,
          vehicles_total: vehicles,
          by_category: TICKET_CATEGORIES.map((category: TicketCategory, k) => ({ category, count: Math.round(total * parts[k]) })),
        };
      });
    });
  }

  getMaintenanceConversionStats(query: Omit<AnalyticsQuery, "category">): Promise<MaintenanceConversionStats> {
    return this.call(() => {
      const { date_from, date_to } = query;
      const range = { date_from, date_to };
      const days = this.days(range) * this.share(query);
      const empty = this.scenario === "empty";
      const tickets = empty ? 0 : Math.round(days * 4.3);
      const withMaintenance = Math.round(tickets * 0.18);
      const recipients = empty ? 0 : Math.round(days * 6.5);
      const opened = Math.round(recipients * 0.62);
      const booked = Math.round(recipients * 0.21);
      return {
        ...range,
        tickets_total: tickets,
        tickets_with_maintenance: withMaintenance,
        ticket_to_maintenance_rate: tickets ? round4(withMaintenance / tickets) : null,
        notifications_recipients: recipients,
        notifications_opened: opened,
        recipients_with_maintenance: booked,
        notification_to_maintenance_rate: recipients ? round4(booked / recipients) : null,
        computed_at: this.computedAt(),
      };
    });
  }

  // ---------- Внутреннее ----------

  private emit(ticketId: number, send: (handlers: TicketLiveHandlers) => void): void {
    for (const handlers of this.watchers.get(ticketId) ?? []) queueMicrotask(() => send(handlers));
  }

  private emitTicket(t: TicketRecord): void {
    const ticket = this.toTicket(t);
    this.emit(t.seed.id, (h) => h.onTicket(clone(ticket)));
  }

  /** Фильтры дашборда в прототипе уменьшают объём пропорционально (модель — треть, категория — пятая часть). */
  private share(query: Partial<AnalyticsQuery>): number {
    return (query.vehicle_model_id === undefined ? 1 : 1 / 3) * (query.category === undefined ? 1 : 1 / 5);
  }

  private user(userId: number): UserPublic {
    const u = this.users.find((x) => x.id === userId);
    if (!u) throw new ApiError("USER_NOT_FOUND", "Пользователь не найден", 404);
    return u;
  }

  /** Клиенты-получатели: владельцы авто модели или все активные клиенты. */
  private audience(modelId: number | null): number {
    const owners =
      modelId === null
        ? this.users.filter((u) => u.role === "client" && u.is_active).map((u) => u.id)
        : VEHICLES.filter((v) => v.modelId === modelId).map((v) => v.ownerId);
    return new Set(owners).size;
  }

  private snapshot(a: KnowledgeArticle, publishedAt: string): KnowledgeArticleRevision {
    return {
      article_id: a.id,
      version: a.version,
      title: a.title,
      published_at: publishedAt,
      content: a.content ?? "",
      category: a.category ?? null,
      vehicle_model_id: a.vehicle_model_id ?? null,
      firmware_release_id: a.firmware_release_id ?? null,
      decision_tree: clone(this.nodesOf(a.id)),
    };
  }

  private nodesOf(articleId: number): DecisionTreeNode[] {
    return this.treeNodes.filter((n) => n.article_id === articleId);
  }

  /** Дерево опубликованной статьи не меняется (`409 ARTICLE_PUBLISHED`, ADR 0018) — сначала снять с публикации. */
  private editableTree(articleId: number): KnowledgeArticle {
    const a = this.article(articleId);
    if (a.is_published) throw new ApiError("ARTICLE_PUBLISHED", "Дерево опубликованной статьи не меняется", 409);
    return a;
  }

  private computedAt(): string {
    return new Date(this.clock().getTime() - ANALYTICS_LAG_MS).toISOString();
  }

  private async call<T>(fn: () => T): Promise<T> {
    if (this.latencyMs > 0) await new Promise((resolve) => setTimeout(resolve, this.latencyMs));
    else await Promise.resolve();
    if (this.offline) throw new ApiError("NETWORK", "Нет соединения с сервером", 0);
    return clone(fn());
  }

  private ticket(ticketId: number): TicketRecord {
    const t = this.tickets.find((x) => x.seed.id === ticketId);
    if (!t) throw new ApiError("NOT_FOUND", `Тикет #${ticketId} не найден`, 404);
    return t;
  }

  private toTicket(t: TicketRecord): Ticket {
    const overdue = t.status !== "resolved" && this.clock().getTime() > Date.parse(t.sla_due_at);
    return {
      id: t.seed.id,
      vehicle_id: t.seed.vehicle_id,
      vehicle_model: this.vehicle(t).vehicle_model,
      summary: t.seed.description.slice(0, SUMMARY_LENGTH),
      category: t.seed.category,
      status: t.status,
      assigned_engineer_id: t.assigned_engineer_id,
      sla_due_at: t.sla_due_at,
      is_overdue: overdue,
      created_at: t.created_at,
      resolved_at: t.resolved_at,
    };
  }

  private toDetail(t: TicketRecord): TicketDetail {
    const vehicle = this.vehicle(t);
    return {
      ...this.toTicket(t),
      description: t.seed.description,
      // Снимок прошивки при создании (N-09); в прототипе прошивка авто не меняется — совпадает с текущей.
      firmware_version_at_creation: vehicle.current_firmware_version ?? null,
      // Эскалация из дерева решений (ADR 0018 п. 11) — тикеты фикстур созданы не из базы знаний.
      source_article: null,
      attachments: [],
      vehicle_context: { vehicle: clone(vehicle), aggregate_statuses: clone(this.statuses[vehicle.id] ?? []) },
    };
  }

  /** Авто, которое инженер может менять: по своему нерешённому тикету (как backend, ADR 0014). */
  private vehicleForChange(vehicleId: number): Vehicle {
    const own = this.tickets.some(
      (t) =>
        t.seed.vehicle_id === vehicleId &&
        t.status !== "resolved" &&
        (this.role === "admin" || t.assigned_engineer_id === ENGINEER_ID),
    );
    if (!own) throw new ApiError("FORBIDDEN", "Авто меняет инженер, назначенный на нерешённый тикет", 403);
    return this.vehicles.find((v) => v.id === vehicleId)!;
  }

  private addRecord(
    vehicleId: number,
    code: string | null,
    at: string,
    mileage: number,
    description: string | null,
    kind: MaintenanceRecord["kind"],
  ): MaintenanceRecord {
    const record: MaintenanceRecord = {
      id: this.nextId++,
      aggregate_type_code: code,
      performed_by: USERS[this.role === "admin" ? ADMIN_ID : ENGINEER_ID],
      performed_at: at,
      mileage_at_service: mileage,
      description,
      kind,
    };
    // История — новые сверху (по дате работы, как listMaintenanceRecords).
    const list = (this.records[vehicleId] ??= []);
    list.push(record);
    list.sort((a, b) => b.performed_at.localeCompare(a.performed_at) || b.id - a.id);
    return record;
  }

  private vehicle(t: TicketRecord): Vehicle {
    return this.vehicles.find((v) => v.id === t.seed.vehicle_id)!;
  }

  private article(articleId: number): KnowledgeArticle {
    const a = this.articles.find((x) => x.id === articleId);
    if (!a) throw new ApiError("NOT_FOUND", "Статья не найдена", 404);
    return a;
  }

  private checkArticle(title: string, content: string) {
    if (!title.trim()) throw validation("Введите заголовок", "title");
    if (title.length > 200) throw validation("Заголовок — не длиннее 200 символов", "title");
    if (!content.trim()) throw validation("Введите текст статьи", "content");
  }


  private days(range: DateRange): number {
    const ms = Date.parse(range.date_to) - Date.parse(range.date_from);
    return Math.max(1, Math.round(ms / 86_400_000) + 1);
  }
}
