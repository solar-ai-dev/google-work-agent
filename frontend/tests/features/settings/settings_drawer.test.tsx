import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { SettingsDrawer } from "../../../src/features/settings/settings_drawer";
import * as settingsApi from "../../../src/features/settings/api/get_settings";
import * as googleApi from "../../../src/features/settings/api/google_connection_operations";
import * as credentialApi from "../../../src/features/settings/api/llm_credential_operations";
import * as backupApi from "../../../src/features/settings/api/backup_operations";

vi.mock("../../../src/features/settings/api/get_settings", () => ({ getSettings: vi.fn() }));
vi.mock("../../../src/features/settings/api/google_connection_operations", () => ({ getGoogleConnection: vi.fn(), startGoogleConnection: vi.fn(), disconnectGoogle: vi.fn() }));
vi.mock("../../../src/features/settings/api/llm_credential_operations", () => ({ getLlmCredentialStatus: vi.fn(), storeLlmCredential: vi.fn(), deleteLlmCredential: vi.fn() }));
vi.mock("../../../src/features/settings/api/backup_operations", () => ({ listBackups: vi.fn(), createBackup: vi.fn(), restoreBackup: vi.fn() }));
vi.mock("../../../src/features/settings/api/update_settings", () => ({ updateSettings: vi.fn() }));
vi.mock("../../../src/features/settings/api/update_runtime_mode", () => ({ updateRuntimeMode: vi.fn() }));

test("SettingsDrawer loads typed non-secret settings, connection, credentials, and backup inventory", async () => {
  vi.mocked(settingsApi.getSettings).mockResolvedValue({ schema_version: 1, timezone: "Asia/Seoul", default_tasklist_id: null, default_calendar_id: null, preferred_llm_mode: "AUTO", external_llm_consent: false, retention_days: 30, theme: "LIGHT", panel_preferences: { schema_version: 1, right_panel_default_open: false, right_panel_default_tab: "CONVERSATIONS" }, working_day_start_local: "09:00", working_day_end_local: "18:00", include_weekends: false, calendar_buffer_minutes: 10, max_run_execution_ms: 1, max_connector_calls_per_run: 1, max_source_page_calls_per_run: 1, max_detail_fetches_per_run: 1, max_context_tokens_per_run: 1, max_retry_attempts_per_run: 1, circuit_failure_threshold: 1, circuit_open_duration_ms: 1 });
  vi.mocked(googleApi.getGoogleConnection).mockResolvedValue({ schema_version: 1, connector_id: "google", account_id: null, display_email: null, connection_status: "DISCONNECTED", granted_scopes: [], missing_required_scopes: [] });
  vi.mocked(credentialApi.getLlmCredentialStatus).mockResolvedValue({ schema_version: 1, provider: "gemini", configured: false, storage_mode: null, validation_status: "NOT_CONFIGURED" });
  vi.mocked(backupApi.listBackups).mockResolvedValue({ schema_version: 1, items: [] });
  render(<SettingsDrawer runtime={null} theme="light" onThemeChange={vi.fn()} onClose={vi.fn()} onOperationalStateChanged={vi.fn()} />);
  expect(await screen.findByLabelText("작업 설정")).toBeInTheDocument();
  expect(screen.getByLabelText("LLM 자격증명").querySelector('input[type="password"]')).toHaveValue("");
  expect(document.body.textContent).not.toContain("sk-");
});
