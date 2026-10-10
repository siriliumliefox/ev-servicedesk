// Фикстуры прототипа веб-кабинета и админ-панели (Глава 8, ADR 0012). Модели, авто #101/#102, статьи и
// деревья решений, тикет #1042 — те же, что в мобильном прототипе (mobile/lib/data/prototype_repository.dart).
// Время тикетов — относительно `now`, чтобы SLA-фильтры показывали все состояния в любой день.
import type {
  AggregateStatus,
  AggregateType,
  DecisionTreeNode,
  FirmwareRelease,
  KnowledgeArticle,
  MaintenanceRecord,
  MaintenanceRegulation,
  Notification,
  TicketCategory,
  TicketMessage,
  TicketStatus,
  UserPublic,
  Vehicle,
  VehicleModel,
} from "../data/models.ts";

const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

export const ENGINEER_ID = 7;
export const OTHER_ENGINEER_ID = 8;
export const ADMIN_ID = 1;

const user = (id: number, role: UserPublic["role"], phone: string): UserPublic => ({
  id,
  phone,
  role,
  is_active: true,
  telegram_id: null,
  created_at: "2026-01-15T09:00:00Z",
});

export const USERS: Record<number, UserPublic> = {
  [ADMIN_ID]: user(ADMIN_ID, "admin", "+375291000001"),
  [ENGINEER_ID]: user(ENGINEER_ID, "engineer", "+375291000007"),
  [OTHER_ENGINEER_ID]: user(OTHER_ENGINEER_ID, "engineer", "+375291000008"),
  501: user(501, "client", "+375297001501"),
  502: user(502, "client", "+375297001502"),
  503: user(503, "client", "+375297001503"),
  504: user(504, "client", "+375297001504"),
  505: user(505, "client", "+375297001505"),
};

export const VEHICLE_MODELS: VehicleModel[] = [
  { id: 1, brand: "Li Auto", model: "L7", trim: "Max" },
  { id: 2, brand: "Zeekr", model: "001", trim: "You" },
  { id: 3, brand: "Voyah", model: "Free", trim: "EVR" },
];

export const AGGREGATE_TYPES: AggregateType[] = [
  { code: "engine_oil", name: "Масло двигателя" },
  { code: "oil_filter", name: "Масляный фильтр" },
  { code: "air_filter", name: "Воздушный фильтр" },
  { code: "cabin_filter", name: "Салонный фильтр" },
  { code: "gearbox_oil", name: "Масло редуктора" },
  { code: "ac_refrigerant", name: "Фреон кондиционера" },
];

const modelInfo = (id: number) => {
  const { brand, model, trim } = VEHICLE_MODELS.find((m) => m.id === id)!;
  return { brand, model, trim };
};

const vehicle = (id: number, modelId: number, vin: string, mileage: number, firmware: string | null): Vehicle => ({
  id,
  vin,
  mileage,
  is_active: true,
  vehicle_model: modelInfo(modelId),
  current_firmware_version: firmware,
  created_at: "2026-02-01T10:00:00Z",
});

/** Авто и владелец (vehicle_id → client id): тикет создаёт владелец авто. */
export const VEHICLES: { vehicle: Vehicle; modelId: number; ownerId: number }[] = [
  { vehicle: vehicle(101, 1, "LLXAB3CF7SA067890", 41250, "RU 2.4.1"), modelId: 1, ownerId: 501 },
  { vehicle: vehicle(102, 2, "L6TAA2BG4RA012345", 18900, "RU 5.1.0"), modelId: 2, ownerId: 501 },
  { vehicle: vehicle(103, 3, "LDPZZZ1Z2RA000123", 27600, "RU 1.8.0"), modelId: 3, ownerId: 502 },
  { vehicle: vehicle(104, 1, "LLXAB3CF1SA071122", 8800, "RU 2.3.0"), modelId: 1, ownerId: 503 },
  { vehicle: vehicle(105, 2, "L6TAA2BG9RA019876", 52300, null), modelId: 2, ownerId: 504 },
];

const aggName = (code: string) => AGGREGATE_TYPES.find((a) => a.code === code)!.name;

const status = (
  code: string,
  value: AggregateStatus["status"],
  extra: Partial<Omit<AggregateStatus, "aggregate_type_code" | "aggregate_type_name" | "status">> = {},
): AggregateStatus => ({
  aggregate_type_code: code,
  aggregate_type_name: aggName(code),
  status: value,
  percentage: null,
  last_replaced_at: null,
  last_replaced_mileage: null,
  remaining_km: null,
  remaining_days: null,
  ...extra,
});

const st = (pct: number, at: string, mileage: number, km: number | null, days: number | null) => ({
  percentage: pct,
  last_replaced_at: at,
  last_replaced_mileage: mileage,
  remaining_km: km,
  remaining_days: days,
});

/** Статусы агрегатов по авто — результат алгоритма главы 5 (в прототипе — готовые значения). */
export const AGGREGATE_STATUSES: Record<number, AggregateStatus[]> = {
  101: [
    status("engine_oil", "red", st(104.5, "2025-10-02", 30800, -450, -8)),
    status("oil_filter", "yellow", st(82, "2025-12-12", 32700, 1550, 66)),
    status("air_filter", "green", st(35, "2026-06-20", 37750, 9750, 248)),
    status("cabin_filter", "yellow", st(91, "2025-11-01", 31250, 1100, 21)),
    status("gearbox_oil", "green", st(12, "2026-08-30", 36450, 52800, 1072)),
    status("ac_refrigerant", "unknown"),
  ],
  102: [
    status("cabin_filter", "green", st(40, "2026-05-15", 12900, 9000, 217)),
    status("gearbox_oil", "yellow", st(76, "2024-11-20", 1200, 5600, 140)),
    status("ac_refrigerant", "green", st(20, "2026-04-02", 11400, null, 590)),
  ],
  103: [
    status("engine_oil", "yellow", st(88, "2025-12-05", 18800, 1200, 40)),
    status("oil_filter", "yellow", st(88, "2025-12-05", 18800, 1200, 40)),
    status("air_filter", "green", st(44, "2025-12-05", 18800, 11200, 300)),
    status("cabin_filter", "red", st(118, "2025-07-10", 9800, -2800, -95)),
    status("gearbox_oil", "green", st(30, "2025-07-10", 9800, 42200, 900)),
    status("ac_refrigerant", "green", st(25, "2025-07-10", 9800, null, 820)),
  ],
  104: AGGREGATE_TYPES.map((a) => status(a.code, "unknown")),
  105: [
    status("cabin_filter", "red", st(132, "2025-03-01", 28100, -2300, -40)),
    status("gearbox_oil", "green", st(40, "2025-03-01", 28100, 35800, 1000)),
    status("ac_refrigerant", "yellow", st(80, "2023-11-10", 9000, null, 220)),
  ],
};

const record = (
  id: number,
  code: string | null,
  at: string,
  mileage: number,
  description: string | null = null,
): MaintenanceRecord => ({
  id,
  aggregate_type_code: code,
  performed_by: USERS[ENGINEER_ID],
  performed_at: at,
  mileage_at_service: mileage,
  description,
});

export const MAINTENANCE_RECORDS: Record<number, MaintenanceRecord[]> = {
  101: [
    record(1, "gearbox_oil", "2026-08-30", 36450),
    record(2, "air_filter", "2026-06-20", 37750),
    record(3, "oil_filter", "2025-12-12", 32700),
    record(4, "cabin_filter", "2025-11-01", 31250),
    record(5, "engine_oil", "2025-10-02", 30800, "Плановое ТО-2"),
    record(6, "engine_oil", "2024-10-15", 15900),
    record(7, "cabin_filter", "2024-10-15", 15900),
  ],
  102: [
    record(8, "cabin_filter", "2026-05-15", 12900),
    record(9, "ac_refrigerant", "2026-04-02", 11400),
    record(10, "gearbox_oil", "2024-11-20", 1200),
  ],
  103: [
    record(11, null, "2025-12-05", 18800, "ТО-1: масло, фильтры"),
    record(12, null, "2025-07-10", 9800, "Русификация, первичное ТО"),
  ],
  104: [],
  105: [record(13, null, "2025-03-01", 28100, "ТО-2")],
};

interface TicketSeed {
  id: number;
  vehicle_id: number;
  category: TicketCategory;
  status: TicketStatus;
  assigned_engineer_id: number | null;
  /** Смещения от now, мс (отрицательные — в прошлом). */
  created: number;
  slaDue: number;
  resolved?: number;
  description: string;
  messages: { from: "client" | "engineer" | "other"; at: number; body: string }[];
}

/** Тикеты по всем колонкам и состояниям SLA (просрочен / < 1 ч / в норме / закрыт). */
const TICKET_SEEDS: TicketSeed[] = [
  {
    id: 1058,
    vehicle_id: 104,
    category: "app_crash",
    status: "new",
    assigned_engineer_id: null,
    created: -5 * HOUR,
    slaDue: -1 * HOUR,
    description: "После мойки перестал включаться экран мультимедиа, перезагрузки не помогают",
    messages: [{ from: "client", at: -5 * HOUR, body: "После мойки перестал включаться экран мультимедиа. Мягкая и жёсткая перезагрузка не помогли." }],
  },
  {
    id: 1057,
    vehicle_id: 105,
    category: "sim",
    status: "new",
    assigned_engineer_id: null,
    created: -3 * HOUR - 20 * MIN,
    slaDue: 40 * MIN,
    description: "Нет мобильного интернета, значка 4G нет",
    messages: [{ from: "client", at: -3 * HOUR - 20 * MIN, body: "Пропал интернет в машине, значка 4G нет. Баланс SIM положительный." }],
  },
  {
    id: 1056,
    vehicle_id: 103,
    category: "navigation",
    status: "new",
    assigned_engineer_id: null,
    created: -30 * MIN,
    slaDue: 3 * HOUR + 30 * MIN,
    description: "Навигация показывает машину в другом районе",
    messages: [{ from: "client", at: -30 * MIN, body: "Навигация показывает машину в другом районе города, на открытом месте тоже." }],
  },
  {
    id: 1055,
    vehicle_id: 102,
    category: "audio",
    status: "new",
    assigned_engineer_id: null,
    created: -10 * MIN,
    slaDue: 3 * HOUR + 50 * MIN,
    description: "Хрипит левый передний динамик",
    messages: [{ from: "client", at: -10 * MIN, body: "Хрипит левый передний динамик на средней громкости." }],
  },
  {
    id: 1042,
    vehicle_id: 101,
    category: "navigation",
    status: "in_progress",
    assigned_engineer_id: ENGINEER_ID,
    created: -26 * HOUR,
    slaDue: -22 * HOUR,
    description: "Яндекс Навигатор не показывает пробки",
    messages: [
      { from: "client", at: -26 * HOUR, body: "Яндекс Навигатор не показывает пробки, хотя интернет есть" },
      {
        from: "engineer",
        at: -25 * HOUR - 48 * MIN,
        body: "Добрый вечер! Проверьте, пожалуйста, версию навигатора: «Настройки» → «О программе». Пришлите скриншот.",
      },
      { from: "client", at: -2 * HOUR, body: "Версия 6.12. Пробок по-прежнему нет." },
    ],
  },
  {
    id: 1049,
    vehicle_id: 102,
    category: "maintenance",
    status: "in_progress",
    assigned_engineer_id: ENGINEER_ID,
    created: -2 * HOUR,
    slaDue: 2 * HOUR,
    description: "Запись на замену масла в редукторе",
    messages: [{ from: "client", at: -2 * HOUR, body: "Приложение показывает «Скоро менять» для масла редуктора. Можно записаться на субботу?" }],
  },
  {
    id: 1050,
    vehicle_id: 105,
    category: "app_crash",
    status: "in_progress",
    assigned_engineer_id: OTHER_ENGINEER_ID,
    created: -3 * HOUR - 30 * MIN,
    slaDue: 30 * MIN,
    description: "Закрывается приложение камер",
    messages: [
      { from: "client", at: -3 * HOUR - 30 * MIN, body: "Приложение камер кругового обзора закрывается через минуту." },
      { from: "other", at: -3 * HOUR, body: "Очистите кэш приложения камер: «Настройки» → «Приложения». Помогло?" },
    ],
  },
  {
    id: 1038,
    vehicle_id: 104,
    category: "sim",
    status: "waiting_vendor",
    assigned_engineer_id: ENGINEER_ID,
    created: -3 * DAY,
    slaDue: -2 * DAY,
    description: "eSIM не активируется после замены головного устройства",
    messages: [
      { from: "client", at: -3 * DAY, body: "После замены головного устройства eSIM не активируется." },
      { from: "engineer", at: -3 * DAY + 40 * MIN, body: "Передали запрос вендору на перевыпуск профиля eSIM, ответ — до 5 рабочих дней." },
    ],
  },
  {
    id: 1044,
    vehicle_id: 103,
    category: "navigation",
    status: "waiting_vendor",
    assigned_engineer_id: OTHER_ENGINEER_ID,
    created: -20 * HOUR,
    slaDue: 6 * HOUR,
    description: "Нет русской озвучки в навигаторе после обновления",
    messages: [{ from: "client", at: -20 * HOUR, body: "После обновления пропала русская озвучка в навигаторе." }],
  },
  {
    id: 1031,
    vehicle_id: 101,
    category: "audio",
    status: "resolved",
    assigned_engineer_id: ENGINEER_ID,
    created: -4 * DAY,
    slaDue: -4 * DAY + 4 * HOUR,
    resolved: -4 * DAY + 2 * HOUR,
    description: "Пропал звук в навигации",
    messages: [
      { from: "client", at: -4 * DAY, body: "Пропал звук подсказок навигации." },
      { from: "engineer", at: -4 * DAY + 2 * HOUR, body: "Включите «Голосовые подсказки» в настройках навигатора. Закрываю обращение." },
    ],
  },
  {
    id: 1029,
    vehicle_id: 102,
    category: "app_crash",
    status: "resolved",
    assigned_engineer_id: OTHER_ENGINEER_ID,
    created: -5 * DAY,
    slaDue: -5 * DAY + 4 * HOUR,
    resolved: -4 * DAY,
    description: "Перезагружается мультимедиа при подключении телефона",
    messages: [{ from: "client", at: -5 * DAY, body: "Мультимедиа перезагружается при подключении телефона по USB." }],
  },
];

export interface TicketRecord {
  seed: TicketSeed;
  created_at: string;
  sla_due_at: string;
  resolved_at: string | null;
  status: TicketStatus;
  assigned_engineer_id: number | null;
  messages: TicketMessage[];
}

export function seedTickets(now: Date): TicketRecord[] {
  const at = (offset: number) => new Date(now.getTime() + offset).toISOString();
  let messageId = 1;
  return TICKET_SEEDS.map((seed) => {
    const owner = VEHICLES.find((v) => v.vehicle.id === seed.vehicle_id)!.ownerId;
    return {
      seed,
      created_at: at(seed.created),
      sla_due_at: at(seed.slaDue),
      resolved_at: seed.resolved === undefined ? null : at(seed.resolved),
      status: seed.status,
      assigned_engineer_id: seed.assigned_engineer_id,
      messages: seed.messages.map((m) => ({
        id: messageId++,
        author: USERS[m.from === "client" ? owner : m.from === "engineer" ? ENGINEER_ID : OTHER_ENGINEER_ID],
        body: m.body,
        attachments: [],
        created_at: at(m.at),
      })),
    };
  });
}

const article = (
  id: number,
  article_type: KnowledgeArticle["article_type"],
  title: string,
  content: string,
  vehicle_model_id: number | null = null,
  version = 1,
  is_published = true,
): KnowledgeArticle => ({ id, article_type, title, content, vehicle_model_id, firmware_release_id: null, version, is_published });

export const ARTICLES: KnowledgeArticle[] = [
  article(
    1,
    "guide",
    "Мультимедиа после русификации: первые шаги",
    "После русификации интерфейс, голосовые подсказки и клавиатура переведены на русский язык.\n\n" +
      "1. Откройте «Настройки» → «Система» → «Язык» и убедитесь, что выбран «Русский».\n" +
      "2. Войдите в аккаунт приложения EV-ServiceDesk — так мы сможем присылать уведомления о прошивках.\n" +
      "3. Не выполняйте обновление «по воздуху» от производителя: оно может сбросить русификацию.",
    null,
    2,
  ),
  article(
    2,
    "guide",
    "Li Auto L7: как узнать версию прошивки",
    "Версия прошивки указана в «Настройки» → «Об автомобиле» → «Версия ПО».\n\n" +
      "Сверьте её с версией в приложении: при выходе новой прошивки для вашей модели придёт уведомление. " +
      "Обновление выполняется только в сервисном центре — удалённой перепрошивки нет.",
    1,
  ),
  article(
    3,
    "guide",
    "Li Auto L7: Яндекс Навигатор на штатном экране",
    "Навигатор установлен при русификации. Для работы пробок нужен мобильный интернет (SIM-карта автомобиля).\n\n" +
      "Если пробки не отображаются: «Настройки» навигатора → «Карта» → включите «Пробки»; проверьте значок 4G " +
      "в статус-баре. Если карта не загружается — см. «Поддержка» → «Неполадки» → «Навигация не видит GPS».",
    1,
    3,
  ),
  article(
    4,
    "guide",
    "Zeekr 001: голосовой помощник на русском",
    "Скажите «Привет, Зикр», чтобы вызвать помощника. Команды: «Включи климат на 21», «Позвони маме», «Построй маршрут домой».",
    2,
  ),
  article(
    5,
    "guide",
    "Настройка APN для SIM-карты автомобиля",
    "«Настройки» → «Сеть» → «Мобильная сеть» → «Точки доступа». Создайте точку: имя — internet, APN — internet. " +
      "Сохраните и перезагрузите мультимедиа (кнопка громкости на руле, 10 секунд).",
  ),
  article(
    6,
    "guide",
    "Voyah Free: сброс навигации к заводским настройкам",
    "Черновик: порядок сброса уточняется у вендора.",
    3,
    1,
    false,
  ),
  article(10, "troubleshooting", "Завис экран мультимедиа", "Экран не реагирует на касания или показывает чёрный фон."),
  article(11, "troubleshooting", "Пропал звук", "Нет звука из динамиков в музыке, навигации или звонках."),
  article(12, "troubleshooting", "Нет мобильного интернета", "Не работают онлайн-карты, музыка и голосовой помощник."),
  article(13, "troubleshooting", "Навигация не видит GPS", "Метка автомобиля не двигается или стоит не на месте."),
];

const node = (
  id: number,
  article_id: number,
  question_text: string,
  options: { label: string; next_node_id: number | null }[] = [],
  flags: { is_root?: boolean; is_escalation?: boolean } = {},
): DecisionTreeNode => ({
  id,
  article_id,
  question_text,
  options,
  is_root: flags.is_root ?? false,
  is_escalation: flags.is_escalation ?? false,
});

/** Деревья решений: «завис экран → мягкая перезагрузка → жёсткая перезагрузка → тикет» (ТЗ, блок 2). */
export const DECISION_TREE_NODES: DecisionTreeNode[] = [
  node(
    100,
    10,
    "Экран реагирует на касания?",
    [
      { label: "Нет, завис полностью", next_node_id: 101 },
      { label: "Да, но приложения закрываются", next_node_id: 104 },
    ],
    { is_root: true },
  ),
  node(101, 10, "Мягкая перезагрузка: зажмите кнопку громкости на руле на 10 секунд, пока экран не погаснет. Помогло?", [
    { label: "Да, экран работает", next_node_id: 105 },
    { label: "Нет", next_node_id: 102 },
  ]),
  node(102, 10, "Жёсткая перезагрузка: выключите автомобиль, закройте двери и подождите 5 минут, затем включите. Помогло?", [
    { label: "Да, экран работает", next_node_id: 105 },
    { label: "Нет", next_node_id: 103 },
  ]),
  node(
    103,
    10,
    "Похоже, нужна помощь инженера. Создайте обращение — модель авто и версия прошивки прикрепятся автоматически.",
    [],
    { is_escalation: true },
  ),
  node(104, 10, "Очистите кэш: «Настройки» → «Приложения» → выберите приложение → «Очистить кэш». Помогло?", [
    { label: "Да", next_node_id: 105 },
    { label: "Нет", next_node_id: 103 },
  ]),
  node(105, 10, "Отлично! Проблема решена."),
  node(
    110,
    11,
    "Проверьте громкость и режим «Без звука» на экране. Звук появился?",
    [
      { label: "Да", next_node_id: 112 },
      { label: "Нет", next_node_id: 111 },
    ],
    { is_root: true },
  ),
  node(111, 11, "Создайте обращение — инженер проверит аудиосистему удалённо или пригласит на диагностику.", [], {
    is_escalation: true,
  }),
  node(112, 11, "Отлично! Проблема решена."),
  node(
    120,
    12,
    "В статус-баре экрана есть значок сети (4G/LTE)?",
    [
      { label: "Есть", next_node_id: 121 },
      { label: "Нет", next_node_id: 122 },
    ],
    { is_root: true },
  ),
  node(121, 12, "Проверьте баланс и пакет трафика SIM-карты автомобиля у оператора. Интернет заработал?", [
    { label: "Да", next_node_id: 123 },
    { label: "Нет", next_node_id: 122 },
  ]),
  node(122, 12, "Создайте обращение — проверим настройки APN и SIM-карту.", [], { is_escalation: true }),
  node(123, 12, "Отлично! Проблема решена."),
  node(
    130,
    13,
    "Выйдите на открытое место и подождите 2–3 минуты. Метка встала на место?",
    [
      { label: "Да", next_node_id: 132 },
      { label: "Нет", next_node_id: 131 },
    ],
    { is_root: true },
  ),
  node(131, 13, "Создайте обращение — проверим модуль GPS и настройки навигации.", [], { is_escalation: true }),
  node(132, 13, "Отлично! Проблема решена."),
];

/** Интервалы замены (км / месяцы) по моделям. Zeekr 001 — BEV: без ДВС, масла двигателя и фильтров ДВС нет. */
const INTERVALS: Record<string, [number | null, number | null]> = {
  engine_oil: [10000, 12],
  oil_filter: [10000, 12],
  air_filter: [20000, 24],
  cabin_filter: [15000, 12],
  gearbox_oil: [60000, 48],
  ac_refrigerant: [null, 36],
};

export function seedRegulations(): MaintenanceRegulation[] {
  const items: MaintenanceRegulation[] = [];
  let id = 1;
  const add = (modelId: number, code: string, km: number | null, months: number | null, archived = false) =>
    items.push({
      id: id++,
      vehicle_model_id: modelId,
      aggregate_type_code: code,
      interval_km: km,
      interval_months: months,
      is_archived: archived,
    });
  // История пересмотра: у Voyah Free интервал масла был 7 500 км, затем увеличен до 10 000 (ADR 0012, «пересмотр»).
  add(3, "engine_oil", 7500, 12, true);
  for (const [code, [km, months]] of Object.entries(INTERVALS)) add(1, code, km, months);
  for (const code of ["cabin_filter", "gearbox_oil", "ac_refrigerant"]) add(2, code, ...INTERVALS[code]);
  for (const [code, [km, months]] of Object.entries(INTERVALS)) add(3, code, km, months);
  return items;
}

export const FIRMWARE_RELEASES: FirmwareRelease[] = [
  { id: 1, vehicle_model_id: 1, version: "RU 2.3.0", released_at: "2026-05-20" },
  { id: 2, vehicle_model_id: 1, version: "RU 2.4.1", released_at: "2026-09-12" },
  { id: 3, vehicle_model_id: 2, version: "RU 5.1.0", released_at: "2026-08-20" },
  { id: 4, vehicle_model_id: 3, version: "RU 1.8.0", released_at: "2026-07-01" },
];

export function seedNotifications(now: Date): Notification[] {
  const at = (offset: number) => new Date(now.getTime() + offset).toISOString();
  return [
    {
      id: 4,
      type: "promo",
      target_vehicle_model_id: null,
      firmware_release_id: null,
      message: "Скидка 15 % на замену салонного фильтра до конца октября.",
      created_at: at(-2 * DAY),
    },
    {
      id: 3,
      type: "firmware",
      target_vehicle_model_id: 1,
      firmware_release_id: 2,
      message: "Доступна прошивка RU 2.4.1 для Li Auto L7: исправлены пробки в навигаторе. Запишитесь на обновление.",
      created_at: at(-28 * DAY),
    },
    {
      id: 2,
      type: "maintenance",
      target_vehicle_model_id: 3,
      firmware_release_id: null,
      message: "Voyah Free: интервал замены масла двигателя увеличен до 10 000 км.",
      created_at: at(-40 * DAY),
    },
    {
      id: 1,
      type: "news",
      target_vehicle_model_id: null,
      firmware_release_id: null,
      message: "Сервисный центр ETS AUTO в Гомеле работает по субботам с 9:00 до 15:00.",
      created_at: at(-60 * DAY),
    },
  ];
}
