// Кабинет инженера на реальном API (глава 21, ADR 0025 п. 6): операции `EngineerRepository` через
// `ApiSession` (Bearer, refresh, тексты ошибок по коду), события тикета — `openTicketLive`.
// Справочники и история сообщений выгружаются всеми страницами (page_size — максимум контракта, 100).
import type {
  AggregateType,
  KnowledgeArticleList,
  MaintenanceRecordList,
  TicketDetail,
  TicketList,
  TicketMessage,
  TicketStatus,
  UserPublic,
  VehicleModel,
} from "../models.ts";
import type {
  EngineerRepository,
  ListArticlesQuery,
  ListTicketsQuery,
  PageQuery,
  TicketLiveHandlers,
} from "../repository.ts";
import { fetchAllPages } from "../paging.ts";
import type { ApiSession } from "./session.ts";
import { openTicketLive, webSocketUrl, type TicketLiveOptions } from "./ticketLive.ts";

const PAGE_SIZE = 100;

export interface HttpRepositoryOptions {
  /** Подмена WebSocket и видимости вкладки — в тестах. */
  live?: Pick<TicketLiveOptions, "WebSocketImpl" | "visibility" | "random">;
}

export class HttpEngineerRepository implements EngineerRepository {
  private readonly session: ApiSession;
  private readonly options: HttpRepositoryOptions;

  constructor(session: ApiSession, options: HttpRepositoryOptions = {}) {
    this.session = session;
    this.options = options;
  }

  getCurrentUser(): Promise<UserPublic> {
    return this.session.request((c) => c.GET("/me"));
  }

  async searchVehicleModels(): Promise<VehicleModel[]> {
    return fetchAllPages((page) =>
      this.session.request((c) => c.GET("/vehicle-models", { params: { query: { page, page_size: PAGE_SIZE } } })),
    );
  }

  async listAggregateTypes(): Promise<AggregateType[]> {
    return fetchAllPages((page) =>
      this.session.request((c) => c.GET("/aggregate-types", { params: { query: { page, page_size: PAGE_SIZE } } })),
    );
  }

  listKnowledgeArticles(query: ListArticlesQuery = {}): Promise<KnowledgeArticleList> {
    return this.session.request((c) => c.GET("/knowledge-articles", { params: { query } }));
  }

  listTickets(query: ListTicketsQuery = {}): Promise<TicketList> {
    return this.session.request((c) => c.GET("/tickets", { params: { query } }));
  }

  getTicket(ticketId: number): Promise<TicketDetail> {
    return this.session.request((c) => c.GET("/tickets/{ticketId}", { params: { path: { ticketId } } }));
  }

  claimTicket(ticketId: number): Promise<TicketDetail> {
    return this.session.request((c) => c.POST("/tickets/{ticketId}/claim", { params: { path: { ticketId } } }));
  }

  updateTicketStatus(ticketId: number, status: TicketStatus): Promise<TicketDetail> {
    return this.session.request((c) =>
      c.PATCH("/tickets/{ticketId}/status", { params: { path: { ticketId } }, body: { status } }),
    );
  }

  listTicketMessages(ticketId: number, query: { after_id?: number } = {}): Promise<TicketMessage[]> {
    return fetchAllPages((page) =>
      this.session.request((c) =>
        c.GET("/tickets/{ticketId}/messages", {
          params: { path: { ticketId }, query: { ...query, page, page_size: PAGE_SIZE } },
        }),
      ),
    );
  }

  createTicketMessage(ticketId: number, body: string): Promise<TicketMessage> {
    return this.session.request((c) =>
      c.POST("/tickets/{ticketId}/messages", { params: { path: { ticketId } }, body: { body } }),
    );
  }

  listMaintenanceRecords(vehicleId: number, query: PageQuery = {}): Promise<MaintenanceRecordList> {
    return this.session.request((c) =>
      c.GET("/vehicles/{vehicleId}/maintenance-records", { params: { path: { vehicleId }, query } }),
    );
  }

  watchTicket(ticketId: number, handlers: TicketLiveHandlers): () => void {
    return openTicketLive({
      ...this.options.live,
      url: webSocketUrl(this.session.baseUrl, `/tickets/${ticketId}/ws`),
      handlers,
      accessToken: () => this.session.accessToken,
      refresh: () => this.session.refresh(),
    });
  }
}
