import { requestJson } from "../../../api/client";

export type RuntimeSummary = {
  schema_version: 1;
  service_instance_id: string;
  connectors: Array<{ schema_version: 1; connector_id: string; connection_status: "CONNECTING" | "CONNECTED" | "DISCONNECTED" | "REAUTH_REQUIRED" | "UNAVAILABLE"; account_ref: string | null; scope_status: "READY" | "INSUFFICIENT" | "UNKNOWN"; retry_at_ms: number | null }>;
  llm_providers: Array<{ schema_version: 1; provider: string; configured: boolean; availability: "READY" | "UNAVAILABLE" | "DISABLED"; model_id: string | null; error_code: string | null }>;
  component_circuits: Array<Record<string, unknown>>;
  active_run_budget: Record<string, unknown> | null;
  recovery_required: boolean;
  release_version: string;
  frontend_build_version: string;
  api_contract_version: string;
  deployment_profile: string;
  runtime_mode: { schema_version: 1; requested_mode: "AUTO" | "LOCAL_GPU" | "API_LLM"; actual_runtime: "LOCAL_GPU" | "API_LLM" | "MIXED" | null; fallback_reason: string | null };
  database_status: "READY" | "DEGRADED" | "UNAVAILABLE";
  migration_status: "READY" | "PENDING" | "FAILED";
  sse_status: "READY" | "DEGRADED" | "UNAVAILABLE";
  recent_sanitized_error_code: string | null;
  launcher_status: "READY" | "DEGRADED" | "UNAVAILABLE";
  manifest_status: "VALID" | "INVALID" | "UNAVAILABLE";
  session_status: "ESTABLISHED" | "NOT_ESTABLISHED";
  safe_mode: boolean;
  last_backup_status: string | null;
  last_migration_status: string | null;
};

export function getRuntime(): Promise<RuntimeSummary> {
  return requestJson("/api/v1/runtime");
}
