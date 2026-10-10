// Репозиторий прототипа (Глава 8, ADR 0012): операции OpenAPI v1 на фикстурах в памяти, без сети и Docker.
// Ошибки — в формате контракта (`ApiError`: code + HTTP-статус). Правила, которые в продукте проверяет
// backend (переходы статусов тикета, claim 409, валидация дерева решений), здесь — упрощённо; финальные
// правила — главы 12–14.
import type {
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
  KnowledgeArticleUpdateRequest,
  MaintenanceConversionStats,
  MaintenanceRecordList,
  MaintenanceRegulation,
  MaintenanceRegulationCreateRequest,
  Notification,
  NotificationCreateRequest,
  ProblemModelStats,
  TicketCategory,
  TicketDetail,
  TicketList,
  TicketMessage,
  TicketMessageList,
  TicketResolutionStats,
  TicketStatus,
  UserPublic,
  VehicleModel,
} from "../data/models.ts";
import { TICKET_CATEGORIES } from "../data/models.ts";
import {
  ApiError,
  type AdminRepository,
  type EngineerRepository,
  type ListArticlesQuery,
  type ListTicketsQuery,
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

/** Переходы статуса, которые прототип разрешает инженеру. new → in_progress — только через claim. */
const TRANSITIONS: Record<TicketStatus, readonly TicketStatus[]> = {
  new: [],
  in_progress: ["waiting_vendor", "resolved"],
  waiting_vendor: ["in_progress", "resolved"],
  resolved: ["in_progress"],
};

export function allowedTransitions(status: TicketStatus): readonly TicketStatus[] {
  return TRANSITIONS[status];
}

const clone = <T>(value: T): T => structuredClone(value);

const page = <T>(items: T[]) => ({
  items,
  meta: { page: 1, page_size: Math.max(items.length, 20), total_items: items.length, total_pages: 1 },
});

const validation = (message: string, field?: string) => new ApiError("VALIDATION_ERROR", message, 422, field);

export class PrototypeRepository implements EngineerRepository, AdminRepository {
  readonly role: "engineer" | "admin";
  private readonly clock: () => Date;
  private readonly latencyMs: number;
  private offline = false;
  private scenario: PrototypeScenario;

  private tickets: TicketRecord[] = [];
  private articles: KnowledgeArticle[] = [];
  private treeNodes: DecisionTreeNode[] = [];
  private aggregateTypes: AggregateType[] = [];
  private regulations: MaintenanceRegulation[] = [];
  private thresholds: AggregateStatusThresholds = { yellow_from_percent: 70, red_above_percent: 100, updated_at: "" };
  private firmware: FirmwareRelease[] = [];
  private notifications: Notification[] = [];
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
    this.thresholds = { yellow_from_percent: 70, red_above_percent: 100, updated_at: "2026-10-01T08:00:00Z" };
    this.firmware = empty ? [] : clone(FIRMWARE_RELEASES);
    this.notifications = empty ? [] : seedNotifications(now);
  }

  // ---------- Общие ----------

  getCurrentUser(): Promise<UserPublic> {
    return this.call(() => USERS[this.role === "admin" ? ADMIN_ID : ENGINEER_ID]);
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
          (query.vehicle_model_id === undefined || a.vehicle_model_id === null || a.vehicle_model_id === query.vehicle_model_id) &&
          (!needle || `${a.title}\n${a.content}`.toLocaleLowerCase("ru").includes(needle)),
      );
      return page(items);
    });
  }

  // ---------- Инженер: тикеты ----------

  listTickets(query: ListTicketsQuery = {}): Promise<TicketList> {
    return this.call(() => {
      const items = this.tickets
        .map((t) => this.toTicket(t))
        .filter(
          (t) =>
            (query.status === undefined || t.status === query.status) &&
            (query.category === undefined || t.category === query.category) &&
            (query.assigned_engineer_id === undefined || t.assigned_engineer_id === query.assigned_engineer_id) &&
            (query.overdue === undefined || t.is_overdue === query.overdue),
        );
      return page(items);
    });
  }

  getTicket(ticketId: number): Promise<TicketDetail> {
    return this.call(() => this.toDetail(this.ticket(ticketId)));
  }

  claimTicket(ticketId: number): Promise<TicketDetail> {
    return this.call(() => {
      const t = this.ticket(ticketId);
      if (t.assigned_engineer_id !== null && t.assigned_engineer_id !== ENGINEER_ID) {
        throw new ApiError("CONFLICT", "Тикет уже взят в работу другим инженером", 409);
      }
      t.assigned_engineer_id = ENGINEER_ID;
      if (t.status === "new") t.status = "in_progress";
      return this.toDetail(t);
    });
  }

  updateTicketStatus(ticketId: number, status: TicketStatus): Promise<TicketDetail> {
    return this.call(() => {
      const t = this.ticket(ticketId);
      if (this.role === "engineer" && t.assigned_engineer_id !== ENGINEER_ID) {
        throw new ApiError("FORBIDDEN", "Статус меняет инженер, назначенный на тикет", 403);
      }
      if (t.status !== status && !TRANSITIONS[t.status].includes(status)) {
        throw validation(`Переход ${t.status} → ${status} недопустим`, "status");
      }
      t.status = status;
      t.resolved_at = status === "resolved" ? this.clock().toISOString() : null;
      return this.toDetail(t);
    });
  }

  listTicketMessages(ticketId: number): Promise<TicketMessageList> {
    return this.call(() => page(this.ticket(ticketId).messages));
  }

  createTicketMessage(ticketId: number, body: string): Promise<TicketMessage> {
    return this.call(() => {
      const t = this.ticket(ticketId);
      if (this.role === "engineer" && t.assigned_engineer_id !== ENGINEER_ID) {
        throw new ApiError("FORBIDDEN", "Писать в чат может инженер, назначенный на тикет", 403);
      }
      if (!body.trim()) throw validation("Сообщение пустое", "body");
      const message: TicketMessage = {
        id: this.nextId++,
        author: USERS[this.role === "admin" ? ADMIN_ID : ENGINEER_ID],
        body: body.trim(),
        attachments: [],
        created_at: this.clock().toISOString(),
      };
      t.messages.push(message);
      return message;
    });
  }

  listMaintenanceRecords(vehicleId: number): Promise<MaintenanceRecordList> {
    return this.call(() => page(MAINTENANCE_RECORDS[vehicleId] ?? []));
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
      this.thresholds = { yellow_from_percent: y, red_above_percent: r, updated_at: this.clock().toISOString() };
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
      const created: KnowledgeArticle = {
        id: this.nextId++,
        article_type: body.article_type,
        title: body.title.trim(),
        content: body.content,
        vehicle_model_id: body.vehicle_model_id ?? null,
        firmware_release_id: body.firmware_release_id ?? null,
        version: 1,
        is_published: false,
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
        const result = this.validateTree(articleId);
        if (!result.is_valid) throw validation("В дереве решений есть ошибки — исправьте перед публикацией", "is_published");
      }
      const changed = title !== a.title || content !== a.content;
      Object.assign(a, {
        title: title.trim(),
        content,
        is_published: body.is_published ?? a.is_published,
        version: changed ? a.version + 1 : a.version,
      });
      return a;
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
      return this.treeNodes.filter((n) => n.article_id === articleId);
    });
  }

  createDecisionTreeNode(articleId: number, body: DecisionTreeNodeCreateRequest): Promise<DecisionTreeNode> {
    return this.call(() => {
      this.article(articleId);
      if (!body.question_text.trim()) throw validation("Введите текст шага", "question_text");
      const created: DecisionTreeNode = { ...clone(body), id: this.nextId++, article_id: articleId };
      this.treeNodes.push(created);
      return created;
    });
  }

  updateDecisionTreeNode(nodeId: number, body: DecisionTreeNodeCreateRequest): Promise<DecisionTreeNode> {
    return this.call(() => {
      const n = this.treeNodes.find((x) => x.id === nodeId);
      if (!n) throw new ApiError("NOT_FOUND", "Шаг не найден", 404);
      if (!body.question_text.trim()) throw validation("Введите текст шага", "question_text");
      Object.assign(n, clone(body));
      return n;
    });
  }

  deleteDecisionTreeNode(nodeId: number): Promise<void> {
    return this.call(() => {
      this.treeNodes = this.treeNodes.filter((n) => n.id !== nodeId);
    });
  }

  validateDecisionTree(articleId: number): Promise<DecisionTreeValidationResult> {
    return this.call(() => this.validateTree(articleId));
  }

  // ---------- Админ: публикации и прошивки ----------

  createNotification(body: NotificationCreateRequest): Promise<Notification> {
    return this.call(() => {
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

  listPublishedNotifications(): Promise<Notification[]> {
    return this.call(() => this.notifications);
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

  // ---------- Админ: аналитика ----------
  // В прототипе — детерминированные значения, пропорциональные длине периода (не из тикетов фикстур).

  getTicketResolutionStats(range: DateRange): Promise<TicketResolutionStats> {
    return this.call(() => {
      const days = this.days(range);
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

  getMaintenanceConversionStats(range: DateRange): Promise<MaintenanceConversionStats> {
    return this.call(() => {
      const days = this.days(range);
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
        ticket_to_maintenance_rate: tickets ? withMaintenance / tickets : null,
        notifications_recipients: recipients,
        notifications_opened: opened,
        recipients_with_maintenance: booked,
        notification_to_maintenance_rate: recipients ? booked / recipients : null,
      };
    });
  }

  // ---------- Внутреннее ----------

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

  private toTicket(t: TicketRecord) {
    const overdue = t.status !== "resolved" && this.clock().getTime() > Date.parse(t.sla_due_at);
    return {
      id: t.seed.id,
      vehicle_id: t.seed.vehicle_id,
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
    const v = VEHICLES.find((x) => x.vehicle.id === t.seed.vehicle_id)!;
    return {
      ...this.toTicket(t),
      description: t.seed.description,
      attachments: [],
      vehicle_context: { vehicle: v.vehicle, aggregate_statuses: AGGREGATE_STATUSES[v.vehicle.id] ?? [] },
    };
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

  /** Предварительные правила проверки дерева (финальные — глава 14). */
  private validateTree(articleId: number): DecisionTreeValidationResult {
    const nodes = this.treeNodes.filter((n) => n.article_id === articleId);
    const ids = new Set(nodes.map((n) => n.id));
    const issues: DecisionTreeValidationResult["issues"] = [];
    const roots = nodes.filter((n) => n.is_root);
    if (roots.length > 1) for (const r of roots) issues.push({ node_id: r.id, problem: "MULTIPLE_ROOTS" });
    for (const n of nodes) {
      for (const o of n.options ?? []) {
        if (o.next_node_id === null && !n.is_escalation) issues.push({ node_id: n.id, problem: "DEAD_END" });
        if (o.next_node_id !== null && !ids.has(o.next_node_id)) issues.push({ node_id: n.id, problem: "BROKEN_REFERENCE" });
      }
    }
    const reachable = new Set<number>();
    const queue = roots.map((r) => r.id);
    while (queue.length) {
      const id = queue.shift()!;
      if (reachable.has(id)) continue;
      reachable.add(id);
      const n = nodes.find((x) => x.id === id);
      for (const o of n?.options ?? []) if (o.next_node_id !== null && ids.has(o.next_node_id)) queue.push(o.next_node_id);
    }
    for (const n of nodes) if (!reachable.has(n.id)) issues.push({ node_id: n.id, problem: "UNREACHABLE" });
    return { is_valid: issues.length === 0, issues };
  }

  private days(range: DateRange): number {
    const ms = Date.parse(range.date_to) - Date.parse(range.date_from);
    return Math.max(1, Math.round(ms / 86_400_000) + 1);
  }
}
