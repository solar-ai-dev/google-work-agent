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
  session_established: boolean;
  service_instance_id: string;
  api_contract_version: string;
};

export type RuntimeSummary = {
  google: string;
  mcp: string;
  api_llm: string;
  ollama: string;
  deployment_profile: string;
  recovery_required_run_ids: string[];
  open_run_ids: string[];
  google_connection?: Record<string, unknown> | null;
  mcp_runtime?: Record<string, unknown> | null;
  llm?: Record<string, unknown> | null;
  safe_mode?: boolean;
  safe_mode_reason_codes?: string[];
  allowed_operations?: string[];
};

export type RuntimeResponse = {
  summary: RuntimeSummary;
  api_contract_version: string;
};

export type SettingsResponse = {
  settings: Record<string, unknown>;
  api_contract_version: string;
};

export type LLMConnectionResponse = {
  llm: Record<string, unknown>;
  api_contract_version: string;
};

export type LLMApiKeyResponse = {
  credential_state: string;
  api_contract_version: string;
};

export type GoogleConnectionResponse = {
  connected: boolean;
  credential_state: string;
  account_email: string | null;
  display_name: string | null;
  granted_scopes: string[];
  missing_scopes: string[];
  reauth_required: boolean;
  oauth_environment: string;
  last_checked_at_ms: number;
  api_contract_version: string;
};

export type GoogleOAuthStartResponse = {
  flow_id: string;
  authorization_url: string;
  callback_url: string;
  expires_at_ms: number;
  oauth_environment: string;
  scopes: string[];
  api_contract_version: string;
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
  id: string;
  account_id: string;
  title: string;
  updated_at_ms: number;
  created_at_ms: number;
};

export type ConversationListResponse = {
  items: ConversationItem[];
  next_cursor: string | null;
  api_contract_version: string;
};

export type LatestConversationRunResponse = {
  run: {
    run_id: string;
    status: string;
    version: number;
    started_at_ms: number;
  } | null;
  api_contract_version: string;
};

export type RunAction = {
  action_id: string;
  tool_name: string;
  status: string;
  version: number;
  effect_type: string;
  approval_required: boolean;
  verification_policy: string;
  next_allowed_commands: string[];
};

export type ApprovalSnapshot = {
  approval_id: string;
  action_id: string;
  status: string;
  approved_at_ms: number;
  expires_at_ms: number;
};

export type RunSnapshot = {
  run_id: string;
  conversation_id: string;
  status: string;
  version: number;
  entry_mode: string;
  requested_mode: string;
  actual_runtime?: string | null;
  started_at_ms: number;
  finished_at_ms?: number | null;
  active_plan?: {
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
  next_allowed_commands: string[];
  snapshot_version: number;
};

export type RunSnapshotResponse = {
  snapshot: RunSnapshot;
  api_contract_version: string;
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
  applied: boolean;
  result_code: string;
  run_id: string;
  conversation_id: string;
  run_status: string;
  run_version: number;
  user_message_id: string;
  workflow_key: string;
  enqueued: boolean;
  request_replayed: boolean;
  conflict_detail?: string | null;
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
};

export type ResourceItem = {
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
};

export type ResourceListResponse = {
  source: string;
  items: ResourceItem[];
  next_page_token: string | null;
  api_contract_version: string;
};

export type EventEnvelope = {
  eventId: string;
  eventType: string;
  payload: Record<string, unknown>;
};
