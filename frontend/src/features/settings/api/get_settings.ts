import { requestJson } from "../../../api/client";

export type SettingsView = {
  schema_version: 1;
  timezone: string;
  default_tasklist_id: string | null;
  default_calendar_id: string | null;
  preferred_llm_mode: "AUTO" | "LOCAL_GPU" | "API_LLM";
  external_llm_consent: boolean;
  retention_days: number;
  theme: "LIGHT" | "DARK";
  panel_preferences: {
    schema_version: 1;
    right_panel_default_open: boolean;
    right_panel_default_tab: "CONVERSATIONS" | "RESOURCES";
  };
  working_day_start_local: string;
  working_day_end_local: string;
  include_weekends: boolean;
  calendar_buffer_minutes: number;
  max_run_execution_ms: number;
  max_connector_calls_per_run: number;
  max_source_page_calls_per_run: number;
  max_detail_fetches_per_run: number;
  max_context_tokens_per_run: number;
  max_retry_attempts_per_run: number;
  circuit_failure_threshold: number;
  circuit_open_duration_ms: number;
};

export function getSettings(): Promise<SettingsView> {
  return requestJson("/api/v1/settings");
}
