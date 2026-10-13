// Общие операции сотрудника на реальном API (главы 21–22, ADR 0025 п. 6, ADR 0026 п. 2): профиль,
// справочники и выборка тикетов. Кабинет инженера и админ-панель наследуют его — один способ ходить в API
// через `ApiSession`.
import type { AggregateType, KnowledgeArticleList, TicketList, UserPublic, VehicleModel } from "../models.ts";
import type { CommonRepository, ListArticlesQuery, ListTicketsQuery } from "../repository.ts";
import { fetchAllPages } from "../paging.ts";
import type { ApiSession } from "./session.ts";

/** page_size — максимум контракта: справочники выгружаются целиком за меньшее число запросов. */
export const PAGE_SIZE = 100;

export class HttpCommonRepository implements CommonRepository {
  protected readonly session: ApiSession;

  constructor(session: ApiSession) {
    this.session = session;
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

  /** Одна страница выборки: доска инженера, тикеты инженера в карточке пользователя админ-панели. */
  listTickets(query: ListTicketsQuery = {}): Promise<TicketList> {
    return this.session.request((c) => c.GET("/tickets", { params: { query } }));
  }
}
