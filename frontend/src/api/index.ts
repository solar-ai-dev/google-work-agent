import {
  API_CONTRACT_VERSION,
  type ActionCommandResponse,
  type AttachmentDescriptorResponse,
  type BootstrapResponse,
  type CurrentGoogleAccountResponse,
  type GoogleConnectionResponse,
  type GoogleOAuthStartResponse,
  type LLMApiKeyResponse,
  type LLMConnectionResponse,
  type LiveResponse,
  type ReadyResponse,
  type RunCommandResponse,
  type RunContextResponse,
  type RunSnapshot,
  type RuntimeResponse,
  type SettingsResponse,
} from "./contract";
import { requestJson } from "./client";

export function getLive(): Promise<LiveResponse> {
  return requestJson("/health/live");
}

export function getReady(): Promise<ReadyResponse> {
  return requestJson("/health/ready");
}

export function bootstrapSession(payload: {
  bootstrap_secret: string;
}): Promise<BootstrapResponse> {
  return requestJson("/api/v1/session/bootstrap", {
    method: "POST",
    body: {
      schema_version: 1,
      bootstrap_secret: payload.bootstrap_secret,
      frontend_api_contract_version: API_CONTRACT_VERSION,
    },
  });
}

export function getRuntime(): Promise<RuntimeResponse> {
  return requestJson("/api/v1/runtime");
}

export function getSettings(): Promise<SettingsResponse> {
  return requestJson("/api/v1/settings");
}

export function patchSettings(payload: {
  command_id: string;
  preferred_llm_mode?: "AUTO" | "LOCAL_GPU" | "API_LLM";
  external_llm_consent?: boolean;
  default_calendar_id?: string | null;
  default_tasklist_id?: string | null;
  timezone?: string;
}): Promise<SettingsResponse> {
  const { command_id, ...settings_patch } = payload;
  return requestJson("/api/v1/settings", {
    method: "PUT",
    body: {
      schema_version: 1,
      command_id,
      settings_patch: { schema_version: 1, ...settings_patch },
    },
  });
}
export function getLLMConnection(): Promise<LLMConnectionResponse> {
  return requestJson("/api/v1/credentials/llm/gemini");
}

export function storeLLMApiKey(payload: {
  api_key: string;
  storage_mode: "KEYRING" | "SESSION_ONLY";
}): Promise<LLMApiKeyResponse> {
  return requestJson("/api/v1/credentials/llm/gemini", {
    method: "PUT",
    body: { schema_version: 1, command_id: crypto.randomUUID(), ...payload },
  });
}

export function deleteLLMApiKey(): Promise<LLMApiKeyResponse> {
  return requestJson("/api/v1/credentials/llm/gemini", {
    method: "DELETE",
    body: { schema_version: 1, command_id: crypto.randomUUID() },
  });
}

export function getGoogleConnection(): Promise<GoogleConnectionResponse> {
  return requestJson("/api/v1/connections/google/status");
}

export function startGoogleOAuth(): Promise<GoogleOAuthStartResponse> {
  return requestJson("/api/v1/connections/google/start", {
    method: "POST",
    body: { schema_version: 1, command_id: crypto.randomUUID() },
  });
}

export function disconnectGoogle(): Promise<{ schema_version: 1; revocation_attempted: boolean; local_credential_deleted: boolean; connection_status: "DISCONNECTED" | "UNAVAILABLE" }> {
  return requestJson("/api/v1/connections/google/disconnect", {
    method: "POST",
    body: { schema_version: 1, command_id: crypto.randomUUID() },
  });
}

export function getCurrentAccount(): Promise<CurrentGoogleAccountResponse> {
  return requestJson("/api/v1/identity/google-account");
}

export function getRunSnapshot(runId: string): Promise<RunSnapshot> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(runId)}`);
}

export function getRunContext(runId: string): Promise<RunContextResponse> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(runId)}/context`);
}

export function cancelRun(payload: {
  run_id: string;
  command_id: string;
  expected_version: number;
}): Promise<RunCommandResponse> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(payload.run_id)}/cancel`, {
    method: "POST",
    body: {
      command_id: payload.command_id,
      expected_version: payload.expected_version,
      api_contract_version: API_CONTRACT_VERSION,
    },
  });
}

export function resumeRun(payload: {
  run_id: string;
  command_id: string;
  expected_version: number;
  resume_kind: "REAUTH_COMPLETED" | "SAFE_CHECKPOINT_RESUME" | "RECOVERY_RECHECK";
}): Promise<RunCommandResponse> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(payload.run_id)}/resume`, {
    method: "POST",
    body: {
      command_id: payload.command_id,
      expected_version: payload.expected_version,
      resume_kind: payload.resume_kind,
      api_contract_version: API_CONTRACT_VERSION,
    },
  });
}

export function confirmRun(payload: {
  run_id: string;
  command_id: string;
  expected_version: number;
  interrupt_id: string;
  response_kind: "OPTION" | "FREE_TEXT" | "DECLINE";
  selected_option?: string | null;
  free_text?: string | null;
}): Promise<RunCommandResponse> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(payload.run_id)}/confirm`, {
    method: "POST",
    body: {
      command_id: payload.command_id,
      expected_version: payload.expected_version,
      interrupt_id: payload.interrupt_id,
      response_kind: payload.response_kind,
      selected_option: payload.selected_option ?? null,
      free_text: payload.free_text ?? null,
      api_contract_version: API_CONTRACT_VERSION,
    },
  });
}

export function resolveRecovery(payload: {
  run_id: string;
  command_id: string;
  expected_version: number;
  action_id: string;
  resolution_kind: "ACCEPT_PARTIAL" | "CREATE_CORRECTIVE_PLAN";
}): Promise<RunCommandResponse> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(payload.run_id)}/resolve-recovery`, {
    method: "POST",
    body: {
      command_id: payload.command_id,
      expected_version: payload.expected_version,
      action_id: payload.action_id,
      resolution_kind: payload.resolution_kind,
      api_contract_version: API_CONTRACT_VERSION,
    },
  });
}

export function approveAction(payload: {
  action_id: string;
  command_id: string;
  expected_version: number;
  duplicate_acknowledged?: boolean;
  calendar_conflict_acknowledged?: boolean;
}): Promise<ActionCommandResponse> {
  return requestJson(`/api/v1/actions/${encodeURIComponent(payload.action_id)}/approve`, {
    method: "POST",
    body: {
      command_id: payload.command_id,
      expected_version: payload.expected_version,
      duplicate_acknowledged: payload.duplicate_acknowledged ?? false,
      calendar_conflict_acknowledged:
        payload.calendar_conflict_acknowledged ?? false,
      api_contract_version: API_CONTRACT_VERSION,
    },
  });
}

export function rejectAction(payload: {
  action_id: string;
  command_id: string;
  expected_version: number;
  reason_code?: string;
}): Promise<ActionCommandResponse> {
  return requestJson(`/api/v1/actions/${encodeURIComponent(payload.action_id)}/reject`, {
    method: "POST",
    body: {
      command_id: payload.command_id,
      expected_version: payload.expected_version,
      reason_code: payload.reason_code ?? null,
      api_contract_version: API_CONTRACT_VERSION,
    },
  });
}

export function modifyAction(payload: {
  action_id: string;
  command_id: string;
  expected_version: number;
  arguments_patch?: Record<string, unknown>;
}): Promise<ActionCommandResponse> {
  return requestJson(`/api/v1/actions/${encodeURIComponent(payload.action_id)}/modify`, {
    method: "POST",
    body: {
      command_id: payload.command_id,
      expected_version: payload.expected_version,
      arguments_patch: payload.arguments_patch ?? {},
      api_contract_version: API_CONTRACT_VERSION,
    },
  });
}

export function prepareRetry(payload: {
  action_id: string;
  command_id: string;
  expected_version: number;
}): Promise<ActionCommandResponse> {
  return requestJson(`/api/v1/actions/${encodeURIComponent(payload.action_id)}/prepare-retry`, {
    method: "POST",
    body: {
      command_id: payload.command_id,
      expected_version: payload.expected_version,
      api_contract_version: API_CONTRACT_VERSION,
    },
  });
}

export async function stageAttachment(file: File): Promise<AttachmentDescriptorResponse> {
  const body = new FormData();
  body.set("command_id", crypto.randomUUID());
  body.set("file", file, file.name);
  return requestJson("/api/v1/attachments/stage", {
    method: "POST",
    body,
  });
}
