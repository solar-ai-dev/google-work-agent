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
  arguments: Record<string, unknown>;
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

export type ContextPreviewItem = {
  segment_id: string;
  role: "SUPPORTS" | "CONTRADICTS" | "CONTEXT";
  source: "gmail" | "tasks" | "calendar";
  resource_type: string;
  resource_id: string;
  display_label: string;
  excerpt: string | null;
};

export type ContextPreview = {
  schema_version: 1;
  run_id: string;
  retrieval_revision: number;
  items: ContextPreviewItem[];
  gmail_count: number;
  tasks_count: number;
  calendar_count: number;
  adjustment_allowed: boolean;
  allowed_adjustments: ("EXCLUDE_EVIDENCE" | "RETRIEVE_MORE")[];
};

export type ExternalLlmTransferScope = {
  schema_version: 1;
  run_id: string;
  scope_revision: number;
  scope_hash: string;
  source_kinds: string[];
  data_classes: ("USER_REQUEST" | "RESOURCE_METADATA" | "EVIDENCE_EXCERPT" | "PLAN_CONTEXT")[];
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
  context_preview: ContextPreview | null;
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
    message: string;
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
  external_llm_transfer_scope: ExternalLlmTransferScope | null;
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

export type ResourceItemMetadata = {
  subject?: string;
  sender_name?: string | null;
  sender_email?: string | null;
  received_at?: string | null;
  snippet?: string | null;
  has_attachments?: boolean;
  task_status?: "incomplete" | "completed";
  scheduled_date?: string | null;
  completed_at?: string | null;
  tasklist_id?: string;
  start?: string;
  end?: string;
  timezone?: string;
  calendar_id?: string;
  location?: string | null;
};

export type ResourceItem = {
  schema_version: 1;
  selection_handle: string;
  source: "gmail" | "tasks" | "calendar";
  resource_type: "gmail_thread" | "task" | "calendar_event";
  resource_id: string;
  parent_id?: string | null;
  title: string;
  subtitle?: string | null;
  link_url: string | null;
  version: string;
  related_resource_ids: string[];
  metadata: ResourceItemMetadata;
  sender_name?: string | null;
  sender_email?: string | null;
  subject?: string | null;
  received_at?: string | null;
  snippet?: string | null;
};

export type GmailListItemWire = {
  schema_version: 1;
  selection_handle: string;
  resource_id: string;
  subject: string;
  sender_name: string | null;
  sender_email: string | null;
  received_at: string | null;
  snippet: string | null;
  has_attachments: boolean;
};

export type TaskListItemWire = {
  schema_version: 1;
  selection_handle: string;
  resource_id: string;
  title: string;
  task_status: "incomplete" | "completed";
  scheduled_date: string | null;
  completed_at: string | null;
  tasklist_id: string;
};

export type CalendarListItemWire = {
  schema_version: 1;
  selection_handle: string;
  resource_id: string;
  title: string;
  start: string;
  end: string;
  timezone: string;
  calendar_id: string;
  location: string | null;
};

export type ResourceListItemWire = GmailListItemWire | TaskListItemWire | CalendarListItemWire;

export type ResourceListWireResponse = {
  schema_version: 1;
  items: ResourceListItemWire[];
  next_page_token: string | null;
  total_count: number | null;
  projection_version: string;
};

export type ResourceListResponse = Omit<ResourceListWireResponse, "items"> & { items: ResourceItem[] };

export type ResourceCountResponse = {
  schema_version: 1;
  source: "gmail" | "tasks" | "calendar";
  exact_count: number;
  as_of_ms: number;
};

export type GmailAttachmentMetadata = {
  schema_version: 1;
  attachment_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number | null;
};

export type GmailResourceDetailResponse = {
  schema_version: 1;
  resource_id: string;
  message_id: string;
  sender_name: string | null;
  sender_email: string;
  recipients: string[];
  cc: string[];
  subject: string;
  received_at: string;
  body: string;
  attachments: GmailAttachmentMetadata[];
  canonical_url: string;
};

export type TaskResourceDetailResponse = {
  schema_version: 1;
  resource_id: string;
  title: string;
  task_status: "incomplete" | "completed";
  scheduled_date: string | null;
  completed_at: string | null;
  tasklist_id: string;
  notes: string | null;
};

export type CalendarResourceDetailResponse = {
  schema_version: 1;
  resource_id: string;
  title: string;
  start: string;
  end: string;
  timezone: string;
  calendar_id: string;
  attendees: string[];
  location: string | null;
  description: string | null;
};

export type TaskListContainer = {
  schema_version: 1;
  tasklist_id: string;
  title: string;
};

export type CalendarContainer = {
  schema_version: 1;
  calendar_id: string;
  title: string;
  primary: boolean;
};
