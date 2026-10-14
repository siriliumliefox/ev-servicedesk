// Авто клиентов в прототипе: пробег, статусы агрегатов и история ТО (копия фикстур на экземпляр). Замена и работа
// по агрегату — правила backend с теми же кодами ошибок (ADR 0016 п. 1, ADR 0023, контракт replaceAggregateStatus и
// createMaintenanceRecord); кто вправе менять авто — решает PrototypeRepository (по тикетам, ADR 0014).
import type {
  AggregateReplaceRequest,
  AggregateStatus,
  MaintenanceRecord,
  MaintenanceRecordCreateRequest,
  MaintenanceRecordList,
  UserPublic,
  Vehicle,
} from "../data/models.ts";
import { ApiError, type PageQuery } from "../data/repository.ts";
import { AGGREGATE_STATUSES, MAINTENANCE_RECORDS, VEHICLES } from "./fixtures.ts";

const clone = <T>(value: T): T => structuredClone(value);

type RecordFields = Pick<MaintenanceRecord, "aggregate_type_code" | "performed_at" | "mileage_at_service" | "description" | "kind">;

export class Garage {
  private vehicles: Vehicle[] = [];
  private statuses: Record<number, AggregateStatus[]> = {};
  private records: Record<number, MaintenanceRecord[]> = {};
  private readonly nextId: () => number;
  private readonly author: () => UserPublic;

  /** `nextId` — общий счётчик id прототипа, `author` — кто вошёл (инженер или администратор). */
  constructor(nextId: () => number, author: () => UserPublic) {
    this.nextId = nextId;
    this.author = author;
    this.reset();
  }

  reset(): void {
    this.vehicles = VEHICLES.map((v) => clone(v.vehicle));
    this.statuses = clone(AGGREGATE_STATUSES);
    this.records = clone(MAINTENANCE_RECORDS);
  }

  vehicle(vehicleId: number): Vehicle {
    return clone(this.find(vehicleId));
  }

  aggregateStatuses(vehicleId: number): AggregateStatus[] {
    return clone(this.statuses[vehicleId] ?? []);
  }

  /** История — новые сверху, страница как `PaginationMeta`. */
  history(vehicleId: number, query: PageQuery): MaintenanceRecordList {
    const items = this.records[vehicleId] ?? [];
    const size = query.page_size ?? 20;
    const page = query.page ?? 1;
    return {
      items: clone(items.slice((page - 1) * size, page * size)),
      meta: { page, page_size: size, total_items: items.length, total_pages: Math.ceil(items.length / size) },
    };
  }

  /** Замена сбрасывает «светофор» и пишет историю; задним числом — только история (ADR 0016). */
  replace(vehicleId: number, code: string, body: AggregateReplaceRequest, today: string): AggregateStatus {
    const status = (this.statuses[vehicleId] ?? []).find((s) => s.aggregate_type_code === code);
    if (!status) throw new ApiError("AGGREGATE_TYPE_NOT_FOUND", "Неизвестный код агрегата", 404);
    if (body.replaced_at > today) throw new ApiError("REPLACED_AT_IN_FUTURE", "Дата замены в будущем", 422, "replaced_at");
    if (body.mileage_at_replacement > this.find(vehicleId).mileage) {
      throw new ApiError("MILEAGE_AHEAD_OF_VEHICLE", "Пробег замены больше пробега авто", 409);
    }
    this.add(vehicleId, {
      aggregate_type_code: code,
      performed_at: body.replaced_at,
      mileage_at_service: body.mileage_at_replacement,
      description: body.description ?? null,
      kind: "replacement",
    });
    if (!status.last_replaced_at || body.replaced_at >= status.last_replaced_at) {
      // Регламентов авто в прототипе нет — свежая замена всегда 🟢 с нулевой выработкой.
      Object.assign(status, {
        status: "green",
        percentage: 0,
        last_replaced_at: body.replaced_at,
        last_replaced_mileage: body.mileage_at_replacement,
      });
    }
    return clone(status);
  }

  /** Работа без замены или без агрегата: счётчик не трогает, пробег выше текущего поднимает пробег авто. */
  recordWork(vehicleId: number, body: MaintenanceRecordCreateRequest, today: string): MaintenanceRecord {
    const code = body.aggregate_type_code ?? null;
    const description = body.description?.trim() || null;
    if (body.performed_at > today) throw new ApiError("PERFORMED_AT_IN_FUTURE", "Дата работы в будущем", 422, "performed_at");
    if (code === null && description === null) {
      throw new ApiError("MAINTENANCE_SUBJECT_REQUIRED", "Укажите агрегат или описание работы", 422, "description");
    }
    const vehicle = this.find(vehicleId);
    vehicle.mileage = Math.max(vehicle.mileage, body.mileage_at_service);
    const fields = { aggregate_type_code: code, performed_at: body.performed_at, mileage_at_service: body.mileage_at_service };
    return clone(this.add(vehicleId, { ...fields, description, kind: "work" }));
  }

  private find(vehicleId: number): Vehicle {
    const vehicle = this.vehicles.find((v) => v.id === vehicleId);
    if (!vehicle) throw new ApiError("NOT_FOUND", "Авто не найдено", 404);
    return vehicle;
  }

  private add(vehicleId: number, fields: RecordFields): MaintenanceRecord {
    const record: MaintenanceRecord = { id: this.nextId(), performed_by: this.author(), ...fields };
    const list = (this.records[vehicleId] ??= []);
    list.push(record);
    list.sort((a, b) => b.performed_at.localeCompare(a.performed_at) || b.id - a.id);
    return record;
  }
}
