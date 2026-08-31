export const API_CONTRACT_VERSION = "1";

export type ErrorEnvelope = {
  error_code: string;
  user_message: string;
  retryable: boolean;
  request_id: string;
  api_contract_version: string;
  current_state?: string | null;
  detail_code?: string | null;
};

export type StartupCheck = {
  name: string;
  state: string;
  detail?: string | null;
};

export type LiveResponse = {
  status: string;
  service_instance_id: string;
  release_version: string;
  api_contract_version: string;
  occurred_at_ms: number;
};

export type ReadyResponse = {
  status: string;
  checks: StartupCheck[];
  release_version: string;
  api_contract_version: string;
  occurred_at_ms: number;
};

export type BootstrapResponse = {
  schema_version: 1;
  session_established: boolean;
  service_instance_id: string;
  api_contract_version: string;
  compatibility: "COMPATIBLE" | "INCOMPATIBLE";
};

export type RuntimeSummary = {
  schema_version: 1;
  service_instance_id: string;
  connectors: Array<{
    schema_version: 1;
    connector_id: string;
    connection_status: "CONNECTING" | "CONNECTED" | "DISCONNECTED" | "REAUTH_REQUIRED" | "UNAVAILABLE";
    account_ref: string | null;
    scope_status: "READY" | "INSUFFICIENT" | "UNKNOWN";
    retry_at_ms: number | null;
  }>;
  llm_providers: Array<{
    schema_version: 1;
    provider: string;
    configured: boolean;
    availability: "READY" | "UNAVAILABLE" | "DISABLED";
    model_id: string | null;
    error_code: string | null;
  }>;
  component_circuits: Array<Record<string, unknown>>;
  active_run_budget: Record<string, unknown> | null;
  recovery_required: boolean;
  release_version: string;
  frontend_build_version: string;
  api_contract_version: string;
  deployment_profile: string;
  runtime_mode: {
    schema_version: 1;
    requested_mode: "AUTO" | "LOCAL_GPU" | "API_LLM";
    actual_runtime: "LOCAL_GPU" | "API_LLM" | "MIXED" | null;
    fallback_reason: string | null;
  };
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

export type RuntimeResponse = RuntimeSummary;

export type SettingsResponse = {
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

export type LLMConnectionResponse = {
  schema_version: 1;
  provider: string;
  configured: boolean;
  storage_mode: "KEYRING" | "SESSION_ONLY" | null;
  validation_status: "VALID" | "INVALID" | "UNAVAILABLE" | "NOT_CONFIGURED";
};

export type LLMApiKeyResponse = LLMConnectionResponse;

export type GoogleConnectionResponse = {
  schema_version: 1;
  connector_id: string;
  account_id: string | null;
  display_email: string | null;
  connection_status: "CONNECTING" | "CONNECTED" | "DISCONNECTED" | "REAUTH_REQUIRED" | "UNAVAILABLE";
  granted_scopes: string[];
  missing_required_scopes: string[];
};

export type GoogleOAuthStartResponse = {
  schema_version: 1;
  authorization_url: string;
  callback_id: string;
};

export type CurrentGoogleAccountResponse = {
  account: {
    account_id: string;
    email: string;
    display_name?: string | null;
  } | null;
  api_contract_version: string;
};

export type ConversationItem = {
  schema_version: 1;
  conversation_id: string;
  title: string | null;
  latest_message_at_ms: number | null;
  open_run_id: string | null;
};

export type ConversationListResponse = {
  schema_version: 1;
  items: ConversationItem[];
  next_cursor: string | null;
};

export type ConversationMessage = {
  schema_version: 1;
  id: string;
  run_id: string | null;
  role: "USER" | "ASSISTANT" | "SYSTEM";
  content: string;
  created_at_ms: number;
};

export type ConversationHistoryRun = {
  schema_version: 1;
  run_id: string;
  status: string;
  started_at_ms: number;
  finished_at_ms: number | null;
};

export type ConversationHistoryResponse = {
  schema_version: 1;
  conversation: ConversationItem;
  messages: ConversationMessage[];
  runs: ConversationHistoryRun[];
  truncated: boolean;
};

export type RunAction = {
  action_id: string;
  tool_name: string;
  status: string;
  version: number;
  effect_type: string;
  approval_required: boolean;
  verification_policy: string;
  risk: Record<string, unknown>;
  next_allowed_commands: string[];
};

export type ApprovalSnapshot = {
  approval_id: string;
  action_id: string;
  status: string;
  approved_at_ms: number;
  expires_at_ms: number;
};

export type PendingInterrupt = {
  schema_version: 1;
  interrupt_id: string;
  semantic_owner_id:
    | "REQUEST_UNDERSTANDING"
    | "TOOL_ROUTE"
    | "RETRIEVAL"
    | "WORK_ANALYSIS"
    | "PLANNING"
    | "REVIEW";
  question: string;
  options: string[];
  response_mode: "OPTION" | "FREE_TEXT";
};

export type RunSnapshot = {
  run: {
    run_id: string;
    conversation_id: string;
    status: string;
    version: number;
    entry_mode: string;
    requested_mode: string;
    actual_runtime: string | null;
    started_at_ms: number;
    finished_at_ms: number | null;
    next_allowed_commands: string[];
  };
  messages: ConversationMessage[];
  current_plan: {
    plan_id: string;
    revision_no: number;
    status: string;
    summary_text?: string | null;
    created_at_ms: number;
  } | null;
  actions: RunAction[];
  approvals: ApprovalSnapshot[];
  execution_status: {
    action_count: number;
    terminal_action_count: number;
  };
  verification_summary: {
    verified_count: number;
    mismatch_count: number;
  };
  recovery_summary: {
    unknown_result_action_count: number;
  };
  pending_interrupt?: PendingInterrupt | null;
  terminal_result_kind: "SUCCESS" | "PARTIAL" | "BLOCKED" | "FAILED" | "CANCELLED" | "NONE";
  projection_version: number;
};

export type RunContext = {
  run_id: string;
  conversation_id: string;
  workflow_key: string;
  entry_mode: string;
  requested_mode: string;
  status: string;
  version: number;
  request_text: string;
  selected_resource_ids: string[];
};

export type RunContextResponse = {
  context: RunContext | null;
  api_contract_version: string;
};

export type StartRunResponse = {
  run_id: string;
  conversation_id: string;
  langgraph_thread_id: string;
  status: string;
  version: number;
  event_stream_url: string;
};

export type ActionCommandResponse = {
  applied: boolean;
  result_code: string;
  action_id: string;
  action_status: string;
  action_version: number;
  next_allowed_commands: string[];
  conflict_detail?: string | null;
};

export type RunCommandResponse = {
  applied: boolean;
  result_code: string;
  run_id: string;
  run_status: string;
  run_version: number;
  should_enqueue?: boolean | null;
  request_replayed?: boolean | null;
  conflict_detail?: string | null;
  result_kind?: string | null;
};

export type ResourceItem = {
  selection_handle: string;
  source: string;
  resource_type: string;
  resource_id: string;
  parent_id?: string | null;
  title: string;
  subtitle?: string | null;
  link_url: string;
  version: string;
  related_resource_ids: string[];
  metadata: Record<string, unknown>;
  sender_name?: string | null;
  sender_email?: string | null;
  subject?: string | null;
  received_at?: string | null;
  snippet?: string | null;
};

export type ResourceListResponse = {
  source: string;
  items: ResourceItem[];
  next_page_token: string | null;
  api_contract_version: string;
};

export type ResourceCountResponse = {
  source: string;
  total_count: number;
  api_contract_version: string;
};

export type GmailAttachmentMetadata = {
  message_id: string;
  attachment_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number | null;
};

export type AttachmentDescriptorResponse = {
  staged_attachment_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  api_contract_version: string;
};

export type GmailResourceDetailResponse = {
  resource_id: string;
  message_id: string;
  sender_name: string | null;
  sender_email: string | null;
  recipients: string[];
  cc: string[];
  subject: string | null;
  received_at: string | null;
  body: string | null;
  attachments: GmailAttachmentMetadata[];
  canonical_url: string;
  api_contract_version: string;
};

export type EventEnvelope = {
  eventId: string;
  eventType: string;
  payload: Record<string, unknown>;
};
