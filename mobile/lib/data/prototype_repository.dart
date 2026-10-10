// Прототип (глава 7, ADR 0011): ClientRepository на фикстурах в памяти.
// Сценарии ревью — нет сети, аккаунт без авто, одно/несколько авто — переключаются в «Демо».
import 'models.dart';
import 'repository.dart';

/// Набор авто на аккаунте для ревью прототипа.
enum AccountScenario {
  multiple('Несколько'),
  single('Одно авто'),
  empty('Без авто');

  const AccountScenario(this.label);

  final String label;
}

class PrototypeRepository implements ClientRepository {
  PrototypeRepository({
    this.latency = const Duration(milliseconds: 350),
    AccountScenario account = AccountScenario.multiple,
    DateTime? now,
  }) : now = now ?? DateTime(2026, 10, 10, 12) {
    reset(account);
  }

  /// Имитация сети; в тестах — Duration.zero.
  final Duration latency;
  final DateTime now;

  /// Код подтверждения в прототипе (пример из контракта).
  static const demoCode = '1234';
  static const maxCodeAttempts = 5;

  bool offline = false;
  AccountScenario account = AccountScenario.multiple;

  late List<Vehicle> _vehicles;
  late List<Ticket> _tickets;
  late Map<int, List<TicketMessage>> _messages;
  late List<NotificationItem> _notifications;
  int _codeAttempts = 0;
  int _nextId = 1100;

  void reset(AccountScenario scenario) {
    account = scenario;
    _vehicles = switch (scenario) {
      AccountScenario.multiple => [_liL7, _zeekr001],
      AccountScenario.single => [_liL7],
      AccountScenario.empty => [],
    };
    final hasVehicles = _vehicles.isNotEmpty;
    _tickets = hasVehicles ? _demoTickets() : [];
    _messages = hasVehicles ? _demoMessages() : {};
    _notifications = _demoNotifications(withVehicles: hasVehicles);
    _codeAttempts = 0;
  }

  Future<T> _call<T>(T Function() body) async {
    await Future<void>.delayed(latency);
    if (offline) throw const OfflineException();
    return body();
  }

  // ---------- Auth ----------

  @override
  Future<int> requestCode(String phone) => _call(() {
        _codeAttempts = 0;
        return 120;
      });

  @override
  Future<void> verifyCode(String phone, String code, {String? pdPolicyVersion}) => _call(() {
        if (pdPolicyVersion == null) {
          throw const ApiException('PD_CONSENT_REQUIRED', 'Нужно согласие на обработку персональных данных');
        }
        if (_codeAttempts >= maxCodeAttempts) {
          throw const ApiException('RATE_LIMITED', 'Слишком много попыток. Запросите новый код');
        }
        if (code != demoCode) {
          _codeAttempts++;
          final left = maxCodeAttempts - _codeAttempts;
          throw ApiException(
            'INVALID_CODE',
            left > 0 ? 'Неверный код. Осталось попыток: $left' : 'Слишком много попыток. Запросите новый код',
          );
        }
      });

  // ---------- Vehicles ----------

  @override
  Future<List<VehicleModel>> vehicleModels() => _call(() => _models);

  @override
  Future<List<Vehicle>> vehicles() => _call(() => List.unmodifiable(_vehicles));

  @override
  Future<Vehicle> addVehicle(String vin, {int? vehicleModelId}) => _call(() {
        if (_vehicles.any((v) => v.vin == vin) || vin == takenVin) {
          throw const ApiException('CONFLICT', 'Этот VIN уже привязан к другому аккаунту');
        }
        final model = vehicleModelId != null ? _models.firstWhere((m) => m.id == vehicleModelId) : _decodeVin(vin);
        if (model == null) {
          throw const ApiException('VIN_DECODE_FAILED', 'Не удалось определить модель по VIN — выберите её из списка');
        }
        final vehicle = Vehicle(id: _nextId++, vin: vin, mileage: 0, vehicleModel: model);
        _vehicles = [..._vehicles, vehicle];
        return vehicle;
      });

  /// VIN-декодер прототипа — по WMI (первые 3 символа).
  static VehicleModel? _decodeVin(String vin) => switch (vin.substring(0, 3)) {
        'LLX' => _models[0],
        'L6T' => _models[1],
        'LDP' => _models[2],
        _ => null,
      };

  /// VIN, уже привязанный к чужому аккаунту (409).
  static const takenVin = 'LDPZZZ1Z2RA000777';

  @override
  Future<List<AggregateStatusItem>> aggregateStatuses(int vehicleId) =>
      _call(() => _statuses[vehicleId] ?? _newVehicleStatuses);

  @override
  Future<List<MaintenanceRecord>> maintenanceRecords(int vehicleId) => _call(() => _records[vehicleId] ?? const []);

  // ---------- Knowledge base ----------

  @override
  Future<List<KnowledgeArticle>> articles(int vehicleModelId, ArticleType type) => _call(() => _articles
      .where((a) => a.articleType == type && (a.vehicleModelId == null || a.vehicleModelId == vehicleModelId))
      .toList());

  @override
  Future<List<DecisionTreeNode>> decisionTree(int articleId) =>
      _call(() => _trees.where((n) => n.articleId == articleId).toList());

  // ---------- Tickets ----------

  @override
  Future<List<Ticket>> tickets() => _call(() => [..._tickets]..sort((a, b) => b.createdAt.compareTo(a.createdAt)));

  @override
  Future<Ticket> createTicket(TicketDraft draft) => _call(() {
        final ticket = Ticket(
          id: _nextId++,
          vehicleId: draft.vehicleId,
          category: draft.category,
          status: TicketStatus.newTicket,
          description: draft.description,
          createdAt: now,
          attachments: draft.attachments,
        );
        _tickets = [..._tickets, ticket];
        _messages[ticket.id] = [
          TicketMessage(
            id: _nextId++,
            fromClient: true,
            authorName: 'Вы',
            body: draft.description,
            createdAt: now,
            attachments: draft.attachments,
          ),
        ];
        return ticket;
      });

  @override
  Future<List<TicketMessage>> messages(int ticketId) => _call(() => List.unmodifiable(_messages[ticketId] ?? []));

  @override
  Future<TicketMessage> sendMessage(int ticketId, String body, {List<TicketAttachment> attachments = const []}) =>
      _call(() {
        final message = TicketMessage(
          id: _nextId++,
          fromClient: true,
          authorName: 'Вы',
          body: body,
          createdAt: now,
          attachments: attachments,
        );
        _messages[ticketId] = [...?_messages[ticketId], message];
        return message;
      });

  // ---------- Notifications ----------

  @override
  Future<List<NotificationItem>> notifications() =>
      _call(() => [..._notifications]..sort((a, b) => b.createdAt.compareTo(a.createdAt)));

  @override
  Future<void> markNotificationRead(int notificationId) => _call(() {
        _notifications = [
          for (final n in _notifications) n.id == notificationId && !n.isRead ? n.markRead(now) : n,
        ];
      });

  int get unreadCount => _notifications.where((n) => !n.isRead).length;

  // ---------- Фикстуры ----------

  static const _models = [
    VehicleModel(id: 1, brand: 'Li Auto', model: 'L7', trim: 'Max'),
    VehicleModel(id: 2, brand: 'Zeekr', model: '001', trim: 'You'),
    VehicleModel(id: 3, brand: 'Voyah', model: 'Free', trim: 'EVR'),
  ];

  static final _liL7 = Vehicle(
    id: 101,
    vin: 'LLXAB3CF7SA067890',
    mileage: 41250,
    vehicleModel: _models[0],
    currentFirmwareVersion: 'RU 2.4.1',
  );

  static final _zeekr001 = Vehicle(
    id: 102,
    vin: 'L6TAA2BG4RA012345',
    mileage: 18900,
    vehicleModel: _models[1],
    currentFirmwareVersion: 'RU 5.1.0',
  );

  static const _names = {
    'engine_oil': 'Масло двигателя',
    'oil_filter': 'Масляный фильтр',
    'air_filter': 'Воздушный фильтр',
    'cabin_filter': 'Салонный фильтр',
    'gearbox_oil': 'Масло редуктора',
    'ac_refrigerant': 'Фреон кондиционера',
  };

  static AggregateStatusItem _status(
    String code,
    AggregateStatus status, {
    double? pct,
    DateTime? at,
    int? mileage,
    int? km,
    int? days,
  }) =>
      AggregateStatusItem(
        aggregateTypeCode: code,
        aggregateTypeName: _names[code]!,
        status: status,
        percentage: pct,
        lastReplacedAt: at,
        lastReplacedMileage: mileage,
        remainingKm: km,
        remainingDays: days,
      );

  // Li Auto L7 (EREV) — полный набор; все статусы светофора, включая «нет данных».
  // Zeekr 001 (BEV) — без ДВС: масла двигателя и фильтров ДВС нет в регламенте модели.
  static final Map<int, List<AggregateStatusItem>> _statuses = {
    101: [
      _status('engine_oil', AggregateStatus.red,
          pct: 104.5, at: DateTime(2025, 10, 2), mileage: 30800, km: -450, days: -8),
      _status('oil_filter', AggregateStatus.yellow,
          pct: 82, at: DateTime(2025, 12, 12), mileage: 32700, km: 1550, days: 66),
      _status('air_filter', AggregateStatus.green,
          pct: 35, at: DateTime(2026, 6, 20), mileage: 37750, km: 9750, days: 248),
      _status('cabin_filter', AggregateStatus.yellow,
          pct: 91, at: DateTime(2025, 11, 1), mileage: 31250, km: 1100, days: 21),
      _status('gearbox_oil', AggregateStatus.green,
          pct: 12, at: DateTime(2026, 8, 30), mileage: 36450, km: 52800, days: 1072),
      _status('ac_refrigerant', AggregateStatus.unknown),
    ],
    102: [
      _status('cabin_filter', AggregateStatus.green,
          pct: 40, at: DateTime(2026, 5, 15), mileage: 12900, km: 9000, days: 217),
      _status('gearbox_oil', AggregateStatus.yellow,
          pct: 76, at: DateTime(2024, 11, 20), mileage: 1200, km: 5600, days: 140),
      _status('ac_refrigerant', AggregateStatus.green,
          pct: 20, at: DateTime(2026, 4, 2), mileage: 11400, km: null, days: 590),
    ],
  };

  // Новое авто без истории ТО — «Нет данных» по всем агрегатам (сценарий главы 5, не ошибка).
  static final _newVehicleStatuses = [
    for (final code in ['engine_oil', 'oil_filter', 'air_filter', 'cabin_filter', 'gearbox_oil', 'ac_refrigerant'])
      _status(code, AggregateStatus.unknown),
  ];

  static final Map<int, List<MaintenanceRecord>> _records = {
    101: [
      MaintenanceRecord(
          id: 1, aggregateTypeCode: 'gearbox_oil', performedAt: DateTime(2026, 8, 30), mileageAtService: 36450),
      MaintenanceRecord(
          id: 2, aggregateTypeCode: 'air_filter', performedAt: DateTime(2026, 6, 20), mileageAtService: 37750),
      MaintenanceRecord(
          id: 3, aggregateTypeCode: 'oil_filter', performedAt: DateTime(2025, 12, 12), mileageAtService: 32700),
      MaintenanceRecord(
          id: 4, aggregateTypeCode: 'cabin_filter', performedAt: DateTime(2025, 11, 1), mileageAtService: 31250),
      MaintenanceRecord(
        id: 5,
        aggregateTypeCode: 'engine_oil',
        performedAt: DateTime(2025, 10, 2),
        mileageAtService: 30800,
        description: 'Плановое ТО-2',
      ),
      MaintenanceRecord(
          id: 6, aggregateTypeCode: 'engine_oil', performedAt: DateTime(2024, 10, 15), mileageAtService: 15900),
      MaintenanceRecord(
          id: 7, aggregateTypeCode: 'cabin_filter', performedAt: DateTime(2024, 10, 15), mileageAtService: 15900),
    ],
    102: [
      MaintenanceRecord(
          id: 8, aggregateTypeCode: 'cabin_filter', performedAt: DateTime(2026, 5, 15), mileageAtService: 12900),
      MaintenanceRecord(
          id: 9, aggregateTypeCode: 'ac_refrigerant', performedAt: DateTime(2026, 4, 2), mileageAtService: 11400),
      MaintenanceRecord(
          id: 10, aggregateTypeCode: 'gearbox_oil', performedAt: DateTime(2024, 11, 20), mileageAtService: 1200),
    ],
  };

  static const _articles = [
    KnowledgeArticle(
      id: 1,
      vehicleModelId: null,
      articleType: ArticleType.guide,
      title: 'Мультимедиа после русификации: первые шаги',
      content: 'После русификации интерфейс, голосовые подсказки и клавиатура переведены на русский язык.\n\n'
          '1. Откройте «Настройки» → «Система» → «Язык» и убедитесь, что выбран «Русский».\n'
          '2. Войдите в аккаунт приложения EV-ServiceDesk — так мы сможем присылать уведомления о прошивках.\n'
          '3. Не выполняйте обновление «по воздуху» от производителя: оно может сбросить русификацию.',
    ),
    KnowledgeArticle(
      id: 2,
      vehicleModelId: 1,
      articleType: ArticleType.guide,
      title: 'Li Auto L7: как узнать версию прошивки',
      content: 'Версия прошивки указана в «Настройки» → «Об автомобиле» → «Версия ПО».\n\n'
          'Сверьте её с версией в приложении: при выходе новой прошивки для вашей модели придёт уведомление. '
          'Обновление выполняется только в сервисном центре — удалённой перепрошивки нет.',
    ),
    KnowledgeArticle(
      id: 3,
      vehicleModelId: 1,
      articleType: ArticleType.guide,
      title: 'Li Auto L7: Яндекс Навигатор на штатном экране',
      content:
          'Навигатор установлен при русификации. Для работы пробок нужен мобильный интернет (SIM-карта автомобиля).\n\n'
          'Если карта не загружается — см. «Поддержка» → «Неполадки» → «Навигация не видит GPS».',
    ),
    KnowledgeArticle(
      id: 4,
      vehicleModelId: 2,
      articleType: ArticleType.guide,
      title: 'Zeekr 001: голосовой помощник на русском',
      content: 'Скажите «Привет, Зикр», чтобы вызвать помощника. Команды: «Включи климат на 21», «Позвони маме», '
          '«Построй маршрут домой».',
    ),
    KnowledgeArticle(
      id: 10,
      vehicleModelId: null,
      articleType: ArticleType.troubleshooting,
      title: 'Завис экран мультимедиа',
      content: 'Экран не реагирует на касания или показывает чёрный фон.',
      category: TicketCategory.appCrash,
    ),
    KnowledgeArticle(
      id: 11,
      vehicleModelId: null,
      articleType: ArticleType.troubleshooting,
      title: 'Пропал звук',
      content: 'Нет звука из динамиков в музыке, навигации или звонках.',
      category: TicketCategory.audio,
    ),
    KnowledgeArticle(
      id: 12,
      vehicleModelId: null,
      articleType: ArticleType.troubleshooting,
      title: 'Нет мобильного интернета',
      content: 'Не работают онлайн-карты, музыка и голосовой помощник.',
      category: TicketCategory.sim,
    ),
    KnowledgeArticle(
      id: 13,
      vehicleModelId: null,
      articleType: ArticleType.troubleshooting,
      title: 'Навигация не видит GPS',
      content: 'Метка автомобиля не двигается или стоит не на месте.',
      category: TicketCategory.navigation,
    ),
  ];

  // Деревья решений: «завис экран → мягкая перезагрузка → жёсткая перезагрузка → тикет» (ТЗ, блок 2).
  static const _trees = [
    DecisionTreeNode(
      id: 100,
      articleId: 10,
      isRoot: true,
      questionText: 'Экран реагирует на касания?',
      options: [
        DecisionTreeOption(label: 'Нет, завис полностью', nextNodeId: 101),
        DecisionTreeOption(label: 'Да, но приложения закрываются', nextNodeId: 104),
      ],
    ),
    DecisionTreeNode(
      id: 101,
      articleId: 10,
      questionText:
          'Мягкая перезагрузка: зажмите кнопку громкости на руле на 10 секунд, пока экран не погаснет. Помогло?',
      options: [
        DecisionTreeOption(label: 'Да, экран работает', nextNodeId: 105),
        DecisionTreeOption(label: 'Нет', nextNodeId: 102),
      ],
    ),
    DecisionTreeNode(
      id: 102,
      articleId: 10,
      questionText:
          'Жёсткая перезагрузка: выключите автомобиль, закройте двери и подождите 5 минут, затем включите. Помогло?',
      options: [
        DecisionTreeOption(label: 'Да, экран работает', nextNodeId: 105),
        DecisionTreeOption(label: 'Нет', nextNodeId: 103),
      ],
    ),
    DecisionTreeNode(
      id: 103,
      articleId: 10,
      isEscalation: true,
      questionText:
          'Похоже, нужна помощь инженера. Создайте обращение — модель авто и версия прошивки прикрепятся автоматически.',
    ),
    DecisionTreeNode(
      id: 104,
      articleId: 10,
      questionText: 'Очистите кэш: «Настройки» → «Приложения» → выберите приложение → «Очистить кэш». Помогло?',
      options: [
        DecisionTreeOption(label: 'Да', nextNodeId: 105),
        DecisionTreeOption(label: 'Нет', nextNodeId: 103),
      ],
    ),
    DecisionTreeNode(id: 105, articleId: 10, questionText: 'Отлично! Проблема решена.'),
    DecisionTreeNode(
      id: 110,
      articleId: 11,
      isRoot: true,
      questionText: 'Проверьте громкость и режим «Без звука» на экране. Звук появился?',
      options: [
        DecisionTreeOption(label: 'Да', nextNodeId: 112),
        DecisionTreeOption(label: 'Нет', nextNodeId: 111),
      ],
    ),
    DecisionTreeNode(
      id: 111,
      articleId: 11,
      isEscalation: true,
      questionText: 'Создайте обращение — инженер проверит аудиосистему удалённо или пригласит на диагностику.',
    ),
    DecisionTreeNode(id: 112, articleId: 11, questionText: 'Отлично! Проблема решена.'),
    DecisionTreeNode(
      id: 120,
      articleId: 12,
      isRoot: true,
      questionText: 'В статус-баре экрана есть значок сети (4G/LTE)?',
      options: [
        DecisionTreeOption(label: 'Есть', nextNodeId: 121),
        DecisionTreeOption(label: 'Нет', nextNodeId: 122),
      ],
    ),
    DecisionTreeNode(
      id: 121,
      articleId: 12,
      questionText: 'Проверьте баланс и пакет трафика SIM-карты автомобиля у оператора. Интернет заработал?',
      options: [
        DecisionTreeOption(label: 'Да', nextNodeId: 123),
        DecisionTreeOption(label: 'Нет', nextNodeId: 122),
      ],
    ),
    DecisionTreeNode(
      id: 122,
      articleId: 12,
      isEscalation: true,
      questionText: 'Создайте обращение — проверим настройки APN и SIM-карту.',
    ),
    DecisionTreeNode(id: 123, articleId: 12, questionText: 'Отлично! Проблема решена.'),
    DecisionTreeNode(
      id: 130,
      articleId: 13,
      isRoot: true,
      questionText: 'Выйдите на открытое место и подождите 2–3 минуты. Метка встала на место?',
      options: [
        DecisionTreeOption(label: 'Да', nextNodeId: 132),
        DecisionTreeOption(label: 'Нет', nextNodeId: 131),
      ],
    ),
    DecisionTreeNode(
      id: 131,
      articleId: 13,
      isEscalation: true,
      questionText: 'Создайте обращение — проверим модуль GPS и настройки навигации.',
    ),
    DecisionTreeNode(id: 132, articleId: 13, questionText: 'Отлично! Проблема решена.'),
  ];

  List<Ticket> _demoTickets() => [
        Ticket(
          id: 1042,
          vehicleId: 101,
          category: TicketCategory.navigation,
          status: TicketStatus.inProgress,
          description: 'Яндекс Навигатор не показывает пробки',
          createdAt: DateTime(2026, 10, 8, 18, 40),
        ),
        Ticket(
          id: 1017,
          vehicleId: 101,
          category: TicketCategory.maintenance,
          status: TicketStatus.resolved,
          description: 'Запись на замену воздушного фильтра',
          createdAt: DateTime(2026, 6, 15, 9, 5),
        ),
      ];

  Map<int, List<TicketMessage>> _demoMessages() => {
        1042: [
          TicketMessage(
            id: 1,
            fromClient: true,
            authorName: 'Вы',
            body: 'Яндекс Навигатор не показывает пробки, хотя интернет есть',
            createdAt: DateTime(2026, 10, 8, 18, 40),
            attachments: const [TicketAttachment(fileName: 'screen.jpg', fileType: AttachmentType.photo)],
          ),
          TicketMessage(
            id: 2,
            fromClient: false,
            authorName: 'Инженер Алексей',
            body: 'Добрый вечер! Проверьте, пожалуйста, версию навигатора: «Настройки» → «О программе». '
                'Пришлите скриншот.',
            createdAt: DateTime(2026, 10, 8, 18, 52),
          ),
        ],
        1017: [
          TicketMessage(
            id: 3,
            fromClient: true,
            authorName: 'Вы',
            body: 'Хочу записаться на замену воздушного фильтра',
            createdAt: DateTime(2026, 6, 15, 9, 5),
          ),
          TicketMessage(
            id: 4,
            fromClient: false,
            authorName: 'Инженер Ольга',
            body: 'Записали вас на 20 июня, 10:00. Ждём!',
            createdAt: DateTime(2026, 6, 15, 9, 14),
          ),
        ],
      };

  List<NotificationItem> _demoNotifications({required bool withVehicles}) => [
        if (withVehicles) ...[
          NotificationItem(
            id: 1,
            type: NotificationType.firmware,
            message: 'Вышла прошивка RU 2.5.0 для Li Auto L7\n'
                'Исправлена работа голосового помощника. Обновление — в сервисном центре, запись через «Поддержку».',
            createdAt: DateTime(2026, 10, 9, 10),
          ),
          NotificationItem(
            id: 2,
            type: NotificationType.maintenance,
            message: 'Скоро замена салонного фильтра\nLi Auto L7: осталось около 1 100 км или 21 день.',
            createdAt: DateTime(2026, 10, 7, 9),
          ),
        ],
        NotificationItem(
          id: 3,
          type: NotificationType.promo,
          message: '−20% на заправку кондиционера\nДо 31 октября в ETS AUTO Гомель.',
          createdAt: DateTime(2026, 10, 1, 12),
          readAt: DateTime(2026, 10, 1, 13),
        ),
        NotificationItem(
          id: 4,
          type: NotificationType.news,
          message: 'Новый сервисный центр в Гомеле\nПринимаем электромобили и гибриды всех марок.',
          createdAt: DateTime(2026, 9, 20, 12),
          readAt: DateTime(2026, 9, 21, 8),
        ),
      ];
}
