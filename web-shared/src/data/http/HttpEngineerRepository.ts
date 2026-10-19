// Кабинет инженера на реальном API (глава 21, ADR 0025 п. 6): операции `EngineerRepository` через
// `ApiSession` (Bearer, refresh, тексты ошибок по коду), события тикета — `openTicketLive`.
// Общие операции — `HttpCommonRepository`; история сообщений выгружается всеми страницами.
import type {
  AggregateReplaceRequest,
  AggregateStatus,
  MaintenanceRecord,
  MaintenanceRecordCreateRequest,
  MaintenanceRecordList,
  TicketDetail,
  TicketMessage,
  TicketStatus,
} from "../models.ts";
import type {
  EngineerRepository,
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

  createTicketMessage(ticketId: number, body: string, clientRequestId?: string): Promise<TicketMessage> {
    return this.session.request((c) =>
      c.POST("/tickets/{ticketId}/messages", {
        params: { path: { ticketId } },
        body: { body, client_request_id: clientRequestId },
      }),
    );
  }

  listMaintenanceRecords(vehicleId: number, query: PageQuery = {}): Promise<MaintenanceRecordList> {
    return this.session.request((c) =>
      c.GET("/vehicles/{vehicleId}/maintenance-records", { params: { path: { vehicleId }, query } }),
    );
  }

  replaceAggregateStatus(vehicleId: number, aggregateTypeCode: string, body: AggregateReplaceRequest): Promise<AggregateStatus> {
    return this.session.request((c) =>
      c.POST("/vehicles/{vehicleId}/aggregate-statuses/{aggregateTypeCode}/replace", {
        params: { path: { vehicleId, aggregateTypeCode } },
        body,
      }),
    );
  }

  createMaintenanceRecord(vehicleId: number, body: MaintenanceRecordCreateRequest): Promise<MaintenanceRecord> {
    return this.session.request((c) =>
      c.POST("/vehicles/{vehicleId}/maintenance-records", { params: { path: { vehicleId } }, body }),
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
