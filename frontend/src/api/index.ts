import {
  API_CONTRACT_VERSION,
  type ActionCommandResponse,
  type AttachmentDescriptorResponse,
  type BootstrapResponse,
  type ConversationHistoryResponse,
  type ConversationListResponse,
  type CurrentGoogleAccountResponse,
  type GoogleConnectionResponse,
  type GoogleOAuthStartResponse,
  type GmailResourceDetailResponse,
  type LatestConversationRunResponse,
  type LLMApiKeyResponse,
  type LLMConnectionResponse,
  type LiveResponse,
  type ReadyResponse,
  type ResourceCountResponse,
  type ResourceListResponse,
  type RunCommandResponse,
  type RunContextResponse,
  type RunSnapshotResponse,
  type RuntimeResponse,
  type SettingsResponse,
  type StartRunResponse,
} from "./contract";
import { requestBlob, requestJson } from "./client";

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
  setup_completed?: boolean;
  requested_runtime_mode?: string;
  external_llm_consent?: boolean;
  ollama_endpoint?: string | null;
  approved_model_id?: string | null;
  default_calendar_id?: string | null;
  default_tasklist_id?: string | null;
  timezone?: string;
}): Promise<SettingsResponse> {
  return requestJson("/api/v1/settings", {
    method: "PATCH",
    body: payload,
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
  conversation_id: string;
  account_id: string;
  title: string;
}): Promise<{ conversation_id: string }> {
  return requestJson("/api/v1/conversations", {
    method: "POST",
    body: { ...payload, api_contract_version: API_CONTRACT_VERSION },
  });
}

export function getConversationHistory(conversationId: string): Promise<ConversationHistoryResponse> {
  return requestJson(`/api/v1/conversations/${encodeURIComponent(conversationId)}/history`);
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
  conversation_id: string;
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
  expected_run_version: number;
}): Promise<RunCommandResponse> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(payload.run_id)}/cancel`, {
    method: "POST",
    body: {
      command_id: payload.command_id,
      expected_run_version: payload.expected_run_version,
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
  response_kind: "OPTION_SELECTION" | "FREE_TEXT";
  selected_option_ids?: string[];
  free_text?: string | null;
}): Promise<RunCommandResponse> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(payload.run_id)}/confirm`, {
    method: "POST",
    body: {
      command_id: payload.command_id,
      expected_version: payload.expected_version,
      interrupt_id: payload.interrupt_id,
      response_kind: payload.response_kind,
      selected_option_ids: payload.selected_option_ids ?? [],
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
  ttl_ms?: number;
  duplicate_acknowledged?: boolean;
  calendar_conflict_acknowledged?: boolean;
}): Promise<ActionCommandResponse> {
  return requestJson(`/api/v1/actions/${encodeURIComponent(payload.action_id)}/approve`, {
    method: "POST",
    body: {
      command_id: payload.command_id,
      expected_version: payload.expected_version,
      ttl_ms: payload.ttl_ms ?? 30000,
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
  expected_action_version: number;
}): Promise<ActionCommandResponse> {
  return requestJson(`/api/v1/actions/${encodeURIComponent(payload.action_id)}/prepare-retry`, {
    method: "POST",
    body: {
      command_id: payload.command_id,
      expected_action_version: payload.expected_action_version,
      api_contract_version: API_CONTRACT_VERSION,
    },
  });
}

export function listGmailResources(
  query: string,
  pageToken?: string | null,
  pageSize = 20,
  includeThreadMetadata = true,
): Promise<ResourceListResponse> {
  const search = new URLSearchParams({ query, page_size: String(pageSize) });
  if (pageToken) {
    search.set("page_token", pageToken);
  }
  if (!includeThreadMetadata) {
    search.set("include_thread_metadata", "false");
  }
  return requestJson(`/api/v1/resources/gmail?${search.toString()}`);
}

export function getGmailResourceDetail(resourceId: string): Promise<GmailResourceDetailResponse> {
  return requestJson(`/api/v1/resources/gmail/${encodeURIComponent(resourceId)}`);
}

export async function stageAttachment(file: File): Promise<AttachmentDescriptorResponse> {
  const bytes = new Uint8Array(await readFileBuffer(file));
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return requestJson("/api/v1/attachments/stage", {
    method: "POST",
    body: {
      filename: file.name,
      mime_type: file.type || "application/octet-stream",
      data_base64: btoa(binary),
    },
  });
}

function readFileBuffer(file: File): Promise<ArrayBuffer> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      if (reader.result instanceof ArrayBuffer) resolve(reader.result);
      else reject(new Error("Attachment file could not be read."));
    });
    reader.addEventListener("error", () => reject(reader.error ?? new Error("Attachment file could not be read.")));
    reader.readAsArrayBuffer(file);
  });
}

export function downloadGmailAttachment(
  messageId: string,
  attachmentId: string,
): Promise<Blob> {
  return requestBlob(
    `/api/v1/gmail/messages/${encodeURIComponent(messageId)}/attachments/${encodeURIComponent(attachmentId)}`,
  );
}

export function listTaskResources(
  taskListId?: string | null,
  pageToken?: string | null,
  pageSize = 100,
  refresh = false,
  statusScope: "incomplete" | "completed" = "incomplete",
): Promise<ResourceListResponse> {
  const search = new URLSearchParams({ page_size: String(pageSize) });
  if (taskListId) {
    search.set("task_list_id", taskListId);
  }
  if (pageToken) {
    search.set("page_token", pageToken);
  }
  if (refresh) search.set("refresh", "true");
  if (statusScope === "completed") search.set("status_scope", statusScope);
  return requestJson(`/api/v1/resources/tasks?${search.toString()}`);
}

export function listCalendarResources(
  calendarId?: string | null,
  pageToken?: string | null,
  pageSize = 100,
  timeMin?: string | null,
  timeMax?: string | null,
): Promise<ResourceListResponse> {
  const search = new URLSearchParams({ page_size: String(pageSize) });
  if (calendarId) {
    search.set("calendar_id", calendarId);
  }
  if (pageToken) {
    search.set("page_token", pageToken);
  }
  if (timeMin) {
    search.set("time_min", timeMin);
  }
  if (timeMax) {
    search.set("time_max", timeMax);
  }
  return requestJson(`/api/v1/resources/calendar?${search.toString()}`);
}

export function getResourceCount(
  source: "gmail" | "tasks" | "calendar",
  options: {
    query?: string | null;
    taskListId?: string | null;
    calendarId?: string | null;
    timeMin?: string | null;
    timeMax?: string | null;
  } = {},
): Promise<ResourceCountResponse> {
  const search = new URLSearchParams();
  if (options.query) search.set("query", options.query);
  if (options.taskListId) search.set("task_list_id", options.taskListId);
  if (options.calendarId) search.set("calendar_id", options.calendarId);
  if (options.timeMin) search.set("time_min", options.timeMin);
  if (options.timeMax) search.set("time_max", options.timeMax);
  const suffix = search.size ? `?${search.toString()}` : "";
  return requestJson(`/api/v1/resources/${source}/count${suffix}`);
}
