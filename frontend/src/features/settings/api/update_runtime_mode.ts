import { requestJson } from "../../../api/client";

export type RuntimeMode = "AUTO" | "LOCAL_GPU" | "API_LLM";

export function updateRuntimeMode(commandId: string, requestedMode: RuntimeMode): Promise<{ schema_version: 1; requested_mode: RuntimeMode; actual_runtime: "LOCAL_GPU" | "API_LLM" | "MIXED" | null; fallback_reason: string | null }> {
  return requestJson("/api/v1/runtime/mode", { method: "POST", body: { schema_version: 1, command_id: commandId, requested_mode: requestedMode } });
}
