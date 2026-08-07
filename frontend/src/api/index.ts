import {
  API_CONTRACT_VERSION,
  type ActionCommandResponse,
  type BootstrapResponse,
  type ConversationListResponse,
  type CurrentGoogleAccountResponse,
  type GoogleConnectionResponse,
  type GoogleOAuthStartResponse,
  type LatestConversationRunResponse,
  type LLMApiKeyResponse,
  type LLMConnectionResponse,
  type LiveResponse,
  type ReadyResponse,
  type ResourceListResponse,
  type RunCommandResponse,
  type RunContextResponse,
  type RunSnapshotResponse,
  type RuntimeResponse,
  type SettingsResponse,
  type StartRunResponse,
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
  service_instance_id: string;
}): Promise<BootstrapResponse> {
  return requestJson("/api/v1/session/bootstrap", {
    method: "POST",
    body: { ...payload, api_contract_version: API_CONTRACT_VERSION },
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
  requested_runtime_mode?: string;
  external_llm_consent?: boolean;
  ollama_endpoint?: string | null;
  approved_model_id?: string | null;
}): Promise<SettingsResponse> {
  return requestJson("/api/v1/settings", {
    method: "PATCH",
    body: { ...payload, api_contract_version: API_CONTRACT_VERSION },
  });
}

export function getLLMConnection(): Promise<LLMConnectionResponse> {
  return requestJson("/api/v1/llm/connection");
}

export function storeLLMApiKey(payload: {
  api_key: string;
  storage_mode: "KEYRING" | "SESSION_MEMORY";
}): Promise<LLMApiKeyResponse> {
  return requestJson("/api/v1/llm/api-key", {
    method: "POST",
    body: payload,
  });
}

export function deleteLLMApiKey(): Promise<LLMApiKeyResponse> {
  return requestJson("/api/v1/llm/api-key", { method: "DELETE" });
}

export function testLLMConnection(): Promise<LLMConnectionResponse> {
  return requestJson("/api/v1/llm/test", { method: "POST", body: {} });
}

export function getGoogleConnection(): Promise<GoogleConnectionResponse> {
  return requestJson("/api/v1/google/connection");
}

export function startGoogleOAuth(): Promise<GoogleOAuthStartResponse> {
  return requestJson("/api/v1/google/oauth/start", { method: "POST", body: {} });
}

export function disconnectGoogle(): Promise<GoogleConnectionResponse> {
  return requestJson("/api/v1/google/disconnect", { method: "POST", body: {} });
}

export function getCurrentAccount(): Promise<CurrentGoogleAccountResponse> {
  return requestJson("/api/v1/identity/google-account");
}

export function listConversations(accountId: string, cursor?: string | null): Promise<ConversationListResponse> {
  const search = new URLSearchParams({ account_id: accountId });
  if (cursor) {
    search.set("cursor", cursor);
  }
  return requestJson(`/api/v1/conversations?${search.toString()}`);
}

export function createConversation(payload: {
  command_id: string;
  request_hash: string;
  conversation_id: string;
  account_id: string;
  title: string;
}): Promise<{ conversation_id: string }> {
  return requestJson("/api/v1/conversations", {
    method: "POST",
    body: { ...payload, api_contract_version: API_CONTRACT_VERSION },
  });
}

export function getLatestConversationRun(conversationId: string): Promise<LatestConversationRunResponse> {
  return requestJson(`/api/v1/conversations/${encodeURIComponent(conversationId)}/latest-run`);
}

export function getRunSnapshot(runId: string): Promise<RunSnapshotResponse> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(runId)}`);
}

export function getRunContext(runId: string): Promise<RunContextResponse> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(runId)}/context`);
}

export function startRun(payload: {
  command_id: string;
  request_hash: string;
  conversation_id: string;
  user_message_id: string;
  run_id: string;
  workflow_key: string;
  request_text: string;
  entry_mode: string;
  selected_resource_ids: string[];
  requested_mode: string;
}): Promise<StartRunResponse> {
  return requestJson("/api/v1/runs", {
    method: "POST",
    body: { ...payload, api_contract_version: API_CONTRACT_VERSION },
  });
}

export function cancelRun(payload: {
  run_id: string;
  command_id: string;
  request_hash: string;
  expected_run_version: number;
}): Promise<RunCommandResponse> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(payload.run_id)}/cancel`, {
    method: "POST",
    body: {
      command_id: payload.command_id,
      request_hash: payload.request_hash,
      expected_run_version: payload.expected_run_version,
      api_contract_version: API_CONTRACT_VERSION,
    },
  });
}

export function resumeRun(payload: {
  run_id: string;
  command_id: string;
  request_hash: string;
  resume_kind: string;
  resume_payload: Record<string, unknown>;
}): Promise<RunCommandResponse> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(payload.run_id)}/resume`, {
    method: "POST",
    body: {
      command_id: payload.command_id,
      request_hash: payload.request_hash,
      resume_kind: payload.resume_kind,
      resume_payload: payload.resume_payload,
      api_contract_version: API_CONTRACT_VERSION,
    },
  });
}

export function approveAction(payload: {
  action_id: string;
  command_id: string;
  request_hash: string;
  expected_version: number;
  approved_by_account_id: string;
  approved_by_display?: string | null;
  source_snapshot: Record<string, unknown>;
  approval_id: string;
  idempotency_key: string;
  ttl_ms?: number;
}): Promise<ActionCommandResponse> {
  return requestJson(`/api/v1/actions/${encodeURIComponent(payload.action_id)}/approve`, {
    method: "POST",
    body: { ...payload, ttl_ms: payload.ttl_ms ?? 30000, api_contract_version: API_CONTRACT_VERSION },
  });
}

export function rejectAction(payload: {
  action_id: string;
  command_id: string;
  request_hash: string;
  expected_version: number;
}): Promise<ActionCommandResponse> {
  return requestJson(`/api/v1/actions/${encodeURIComponent(payload.action_id)}/reject`, {
    method: "POST",
    body: { ...payload, api_contract_version: API_CONTRACT_VERSION },
  });
}

export function modifyAction(payload: {
  action_id: string;
  command_id: string;
  request_hash: string;
  expected_version: number;
}): Promise<ActionCommandResponse> {
  return requestJson(`/api/v1/actions/${encodeURIComponent(payload.action_id)}/modify`, {
    method: "POST",
    body: { ...payload, api_contract_version: API_CONTRACT_VERSION },
  });
}

export function prepareRetry(payload: {
  action_id: string;
  command_id: string;
  request_hash: string;
  expected_action_version: number;
}): Promise<ActionCommandResponse> {
  return requestJson(`/api/v1/actions/${encodeURIComponent(payload.action_id)}/prepare-retry`, {
    method: "POST",
    body: { ...payload, api_contract_version: API_CONTRACT_VERSION },
  });
}

export function listGmailResources(query: string, pageToken?: string | null): Promise<ResourceListResponse> {
  const search = new URLSearchParams({ query, page_size: "20" });
  if (pageToken) {
    search.set("page_token", pageToken);
  }
  return requestJson(`/api/v1/resources/gmail?${search.toString()}`);
}

export function listTaskResources(taskListId?: string | null, pageToken?: string | null): Promise<ResourceListResponse> {
  const search = new URLSearchParams({ page_size: "20" });
  if (taskListId) {
    search.set("task_list_id", taskListId);
  }
  if (pageToken) {
    search.set("page_token", pageToken);
  }
  return requestJson(`/api/v1/resources/tasks?${search.toString()}`);
}

export function listCalendarResources(calendarId?: string | null, pageToken?: string | null): Promise<ResourceListResponse> {
  const search = new URLSearchParams({ page_size: "20" });
  if (calendarId) {
    search.set("calendar_id", calendarId);
  }
  if (pageToken) {
    search.set("page_token", pageToken);
  }
  return requestJson(`/api/v1/resources/calendar?${search.toString()}`);
}
