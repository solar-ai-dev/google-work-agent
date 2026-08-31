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
  required_acknowledgements: ("TASK_DUPLICATE" | "CALENDAR_CONFLICT")[];
  editable_fields: string[];
  attachment_allowed: boolean;
  delivery_certainty: "NOT_SENT" | "MAY_HAVE_BEEN_SENT" | "SENT_RESPONSE_LOST" | null;
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
  recovery?: {
    reason_code: "UNKNOWN_RESULT" | "VERIFICATION_MISMATCH" | "CHECKPOINT_MISMATCH" | "CONTRACT_VIOLATION";
    target: { target_kind: "RUN" } | { target_kind: "ACTION"; action_id: string };
    allowed_resolution_kinds: ("RECHECK" | "ACCEPT_PARTIAL" | "CREATE_CORRECTIVE_PLAN" | "CANCEL" | "FAIL")[];
  } | null;
  error?: {
    schema_version: number;
    error_code: string;
    message: string;
    actions: {
      kind: "PREPARE_RETRY" | "REAUTHENTICATE_GOOGLE" | "RESUME_SAFE_CHECKPOINT" | "OPEN_SETTINGS" | "OPEN_DIAGNOSTICS";
      action_id?: string | null;
      resume_kind?: "SAFE_CHECKPOINT_RESUME" | null;
    }[];
  } | null;
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
