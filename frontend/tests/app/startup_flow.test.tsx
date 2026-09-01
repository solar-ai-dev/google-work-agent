import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { StartupFlow } from "../../src/app/startup_flow";
import * as api from "../../src/api";
import * as runtimeApi from "../../src/features/diagnostics/api/get_runtime";
import * as settingsApi from "../../src/features/settings/api/get_settings";
import * as googleApi from "../../src/features/settings/api/google_connection_operations";
import * as backupApi from "../../src/features/settings/api/backup_operations";
import userEvent from "@testing-library/user-event";

vi.mock("../../src/api", () => ({
  getLive: vi.fn(),
  getReady: vi.fn(),
  bootstrapSession: vi.fn(),
}));
vi.mock("../../src/features/diagnostics/api/get_runtime", () => ({ getRuntime: vi.fn() }));
vi.mock("../../src/features/settings/api/get_settings", () => ({ getSettings: vi.fn() }));
vi.mock("../../src/features/settings/api/google_connection_operations", () => ({ getGoogleConnection: vi.fn(), getCurrentGoogleAccount: vi.fn() }));
vi.mock("../../src/features/settings/api/backup_operations", () => ({ listBackups: vi.fn(), restoreBackup: vi.fn(), requestShutdown: vi.fn() }));

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/");
});

test("blocks every protected query when the public contract version is incompatible", async () => {
  vi.mocked(api.getLive).mockResolvedValue({ api_contract_version: "2" } as never);
  render(<StartupFlow>{() => <p>workspace</p>}</StartupFlow>);

  expect(await screen.findByText(/호환되지 않습니다/)).toBeInTheDocument();
  expect(api.getReady).not.toHaveBeenCalled();
  expect(runtimeApi.getRuntime).not.toHaveBeenCalled();
  expect(settingsApi.getSettings).not.toHaveBeenCalled();
});

test("loads protected state only after readiness and compatible bootstrap", async () => {
  window.history.replaceState(null, "", "/#bootstrap_secret=secret&service_instance_id=service-1");
  vi.mocked(api.getLive).mockResolvedValue({ api_contract_version: "1" } as never);
  vi.mocked(api.getReady).mockResolvedValue({ status: "READY", api_contract_version: "1", checks: [] } as never);
  vi.mocked(api.bootstrapSession).mockResolvedValue({ schema_version: 1, session_established: true, service_instance_id: "service-1", api_contract_version: "1", compatibility: "COMPATIBLE" });
  vi.mocked(runtimeApi.getRuntime).mockResolvedValue({} as never);
  vi.mocked(googleApi.getGoogleConnection).mockResolvedValue({ connection_status: "DISCONNECTED" } as never);
  vi.mocked(settingsApi.getSettings).mockResolvedValue({ timezone: "Asia/Seoul", default_calendar_id: "primary", default_tasklist_id: "@default" } as never);
  vi.mocked(googleApi.getCurrentGoogleAccount).mockResolvedValue({ account: null } as never);

  render(<StartupFlow>{() => <p>workspace</p>}</StartupFlow>);

  expect(await screen.findByText("workspace")).toBeInTheDocument();
  expect(api.bootstrapSession).toHaveBeenCalledWith({ bootstrap_secret: "secret" });
  expect(window.location.hash).toBe("");
  await waitFor(() => expect(runtimeApi.getRuntime).toHaveBeenCalledOnce());
});

test("exposes restore and graceful shutdown while readiness is in Safe Mode", async () => {
  vi.mocked(api.getLive).mockResolvedValue({ api_contract_version: "1" } as never);
  vi.mocked(api.getReady).mockResolvedValue({ status: "SAFE_MODE", api_contract_version: "1", checks: [{ name: "migration", state: "SAFE_MODE", detail: "MIGRATION_FAILED" }] } as never);
  vi.mocked(backupApi.listBackups).mockResolvedValue({ schema_version: 1, items: [{ schema_version: 1, backup_ref: "backup-opaque", created_at_ms: 1, size_bytes: 100, manifest_hash: "a".repeat(64) }] });
  vi.mocked(backupApi.restoreBackup).mockResolvedValue({ schema_version: 1, backup_ref: "backup-opaque", status: "RESTORED", detail_code: null });
  vi.mocked(backupApi.requestShutdown).mockResolvedValue({ schema_version: 1, accepted: true });

  render(<StartupFlow>{() => <p>workspace</p>}</StartupFlow>);
  expect(await screen.findByRole("heading", { name: "Google Work Agent Safe Mode" })).toBeInTheDocument();
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "복원할 백업" }), "backup-opaque");
  await userEvent.click(screen.getByRole("checkbox"));
  await userEvent.click(screen.getByRole("button", { name: "복원 처리" }));
  await waitFor(() => expect(backupApi.restoreBackup).toHaveBeenCalledWith(expect.any(String), "backup-opaque"));
  expect(screen.getByRole("status")).toHaveTextContent("Migration·재시작·준비 상태");
  await userEvent.click(screen.getByRole("button", { name: "안전하게 종료" }));
  await waitFor(() => expect(backupApi.requestShutdown).toHaveBeenCalledOnce());
});
