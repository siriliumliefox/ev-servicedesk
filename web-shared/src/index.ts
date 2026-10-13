export { STATUS_LABELS, StatusBadge, StatusIcon } from "./StatusBadge";
export type { AggregateStatusValue } from "./StatusBadge";
export { Button, Card, TextField } from "./components";
export type { ButtonSize, ButtonVariant } from "./components";
export { useTheme } from "./theme/useTheme";
export type { ThemeName, ThemePreference } from "./theme/useTheme";
export { MOCK_API_BASE_URL, createApiClient } from "./api/client.ts";
export type { ApiClient, components, operations, paths } from "./api/client.ts";

// Глава 8: слой данных, прототип на фикстурах, общие компоненты кабинетов (ADR 0012).
export * from "./data/models.ts";
export * from "./data/labels.ts";
export * from "./data/sla.ts";
export * from "./data/format.ts";
export * from "./data/repository.ts";
export { PrototypeRepository } from "./prototype/PrototypeRepository.ts";
export { allowedTransitions, engineerMoves } from "./data/ticketFlow.ts";
export type { PrototypeOptions, PrototypeScenario } from "./prototype/PrototypeRepository.ts";
export { ENGINEER_ID, OTHER_ENGINEER_ID, ADMIN_ID } from "./prototype/fixtures.ts";
export { Badge, Chip, Select, TextArea } from "./ui/controls.tsx";
export type { BadgeTone } from "./ui/controls.tsx";
export { EmptyState, ErrorState, InlineError, LoadingState } from "./ui/feedback.tsx";
export { useAsync, useHashRoute } from "./ui/hooks.ts";
export type { AsyncState } from "./ui/hooks.ts";
export { DemoPanel } from "./ui/DemoPanel.tsx";

// Глава 21: реальный API (ADR 0025 п. 6) — сессия сотрудника, HTTP-репозиторий, события тикета.
export * from "./data/errors.ts";
export * from "./data/paging.ts";
export { ApiSession, memoryTokenStore, sessionTokenStore } from "./data/http/session.ts";
export type { ApiSessionOptions, SessionEnd, TokenStore } from "./data/http/session.ts";
export { HttpCommonRepository } from "./data/http/HttpCommonRepository.ts";
export { HttpEngineerRepository } from "./data/http/HttpEngineerRepository.ts";
export { HttpAdminRepository } from "./data/http/HttpAdminRepository.ts";
export type { HttpRepositoryOptions } from "./data/http/HttpEngineerRepository.ts";
export { openTicketLive, webSocketUrl } from "./data/http/ticketLive.ts";
export { StaffSessionGate, ThemeSelect } from "./ui/StaffSessionGate.tsx";
export type { StaffSessionGateProps } from "./ui/StaffSessionGate.tsx";
export type { TicketLiveOptions, Visibility } from "./data/http/ticketLive.ts";
