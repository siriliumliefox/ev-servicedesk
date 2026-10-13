// Кабинет инженера на реальном API (глава 21, ADR 0025 п. 6): операции `EngineerRepository` через
// `ApiSession` (Bearer, refresh, тексты ошибок по коду), события тикета — `openTicketLive`.
// Общие операции — `HttpCommonRepository`; история сообщений выгружается всеми страницами.
import type { MaintenanceRecordList, TicketDetail, TicketList, TicketMessage, TicketStatus } from "../models.ts";
import type {
  EngineerRepository,
  ListTicketsQuery,
  PageQuery,
  TicketLiveHandlers,
} from "../repository.ts";
import { fetchAllPages } from "../paging.ts";
import { HttpCommonRepository, PAGE_SIZE } from "./HttpCommonRepository.ts";
import type { ApiSession } from "./session.ts";
import { openTicketLive, webSocketUrl, type TicketLiveOptions } from "./ticketLive.ts";

export interface HttpRepositoryOptions {
  /** Подмена WebSocket и видимости вкладки — в тестах. */
  live?: Pick<TicketLiveOptions, "WebSocketImpl" | "visibility" | "random">;
}

export class HttpEngineerRepository extends HttpCommonRepository implements EngineerRepository {
  private readonly options: HttpRepositoryOptions;

  constructor(session: ApiSession, options: HttpRepositoryOptions = {}) {
    super(session);
    this.options = options;
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
