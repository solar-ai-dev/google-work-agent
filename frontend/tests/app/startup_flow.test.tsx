import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { StartupFlow } from "../../src/app/startup_flow";
import * as api from "../../src/api";
import * as runtimeApi from "../../src/features/diagnostics/api/get_runtime";
import * as settingsApi from "../../src/features/settings/api/get_settings";
import * as googleApi from "../../src/features/settings/api/google_connection_operations";

vi.mock("../../src/api", () => ({
  getLive: vi.fn(),
  getReady: vi.fn(),
  bootstrapSession: vi.fn(),
}));
vi.mock("../../src/features/diagnostics/api/get_runtime", () => ({ getRuntime: vi.fn() }));
vi.mock("../../src/features/settings/api/get_settings", () => ({ getSettings: vi.fn() }));
vi.mock("../../src/features/settings/api/google_connection_operations", () => ({ getGoogleConnection: vi.fn(), getCurrentGoogleAccount: vi.fn() }));

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
