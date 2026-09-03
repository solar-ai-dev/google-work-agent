export const RUN_SSE_EVENT_TYPES = [
  "run_status", "phase_changed", "tool_routing", "retrieval_progress",
  "confirmation_required", "analysis_progress", "plan_updated", "approval_required",
  "action_status", "verification_result", "reauth_required", "recovery_required",
  "completed", "error",
] as const;

export type RunSseEventType = typeof RUN_SSE_EVENT_TYPES[number];

type RunStatus = "CREATED" | "ANALYZING" | "RETRIEVING" | "WAITING_CONFIRMATION" | "PLANNING" | "WAITING_APPROVAL" | "EXECUTING" | "VERIFYING" | "COMPLETED" | "CANCEL_REQUESTED" | "CANCELLED" | "REAUTH_REQUIRED" | "RECOVERY_REQUIRED" | "FAILED" | "BLOCKED";
type WorkflowPhase = "INITIALIZE" | "REQUEST_ANALYSIS" | "TOOL_ROUTING" | "WAITING_CONFIRMATION" | "CONTEXT_RETRIEVAL" | "WORK_ANALYSIS" | "SOLUTION_PLANNING" | "PLAN_REVIEW" | "DOMAIN_VALIDATION" | "WAITING_APPROVAL" | "PREFLIGHT" | "ACTION_EXECUTION" | "READ_EXECUTION" | "VERIFICATION" | "RESPONSE_SYNTHESIS" | "RECOVERY" | "FINALIZE";
type ActionStatus = "PROPOSED" | "MODIFIED" | "APPROVED" | "REJECTED" | "EXPIRED" | "EXECUTING" | "UNKNOWN_RESULT" | "EXECUTED" | "VERIFIED" | "FAILED" | "BLOCKED" | "DEPENDENCY_BLOCKED" | "MISMATCH" | "CANCELLED";
type RecoveryResolution = "RECHECK" | "ACCEPT_PARTIAL" | "CREATE_CORRECTIVE_PLAN" | "CANCEL" | "FAIL";

export type RunSsePayloadByType = {
  run_status: { status: RunStatus; snapshot_version: number };
  phase_changed: { phase: WorkflowPhase };
  tool_routing: { route_revision: number; input_route_count: number; output_mode: "ANSWER" | "ACTION" };
  retrieval_progress: { coverage: "NONE" | "PARTIAL" | "SUFFICIENT"; completed_sources: number; total_sources: number };
  confirmation_required: { interrupt_id: string; question: string; options: string[] };
  analysis_progress: { completed_stage: string };
  plan_updated: { plan_id: string | null; revision_no: number };
  approval_required: { action_ids: string[] };
  action_status: { action_id: string; status: ActionStatus };
  verification_result: { action_id: string; outcome: "VERIFIED" | "MISMATCH" };
  reauth_required: { connector_id: string };
  recovery_required: { recovery: {
    reason_code: "UNKNOWN_RESULT" | "VERIFICATION_MISMATCH" | "CHECKPOINT_MISMATCH" | "CONTRACT_VIOLATION";
    target: { target_kind: "RUN" } | { target_kind: "ACTION"; action_id: string };
    allowed_resolution_kinds: RecoveryResolution[];
  } };
  completed: { status: "COMPLETED" | "BLOCKED" | "FAILED" | "CANCELLED"; result_kind: "SUCCESS" | "PARTIAL" | "BLOCKED" | "FAILED" | "CANCELLED" };
  error: { error_code: string; recoverable: boolean };
};

type RunSseEnvelope<K extends RunSseEventType> = {
  schema_version: 1;
  event_id: string;
  run_id: string;
  action_id: string | null;
  occurred_at_ms: number;
  event_type: K;
  payload: RunSsePayloadByType[K];
  projection_version: number;
};

export type RunSseEvent = {
  [K in RunSseEventType]: RunSseEnvelope<K>
}[RunSseEventType];

const RUN_STATUSES: readonly RunStatus[] = ["CREATED", "ANALYZING", "RETRIEVING", "WAITING_CONFIRMATION", "PLANNING", "WAITING_APPROVAL", "EXECUTING", "VERIFYING", "COMPLETED", "CANCEL_REQUESTED", "CANCELLED", "REAUTH_REQUIRED", "RECOVERY_REQUIRED", "FAILED", "BLOCKED"];
const WORKFLOW_PHASES: readonly WorkflowPhase[] = ["INITIALIZE", "REQUEST_ANALYSIS", "TOOL_ROUTING", "WAITING_CONFIRMATION", "CONTEXT_RETRIEVAL", "WORK_ANALYSIS", "SOLUTION_PLANNING", "PLAN_REVIEW", "DOMAIN_VALIDATION", "WAITING_APPROVAL", "PREFLIGHT", "ACTION_EXECUTION", "READ_EXECUTION", "VERIFICATION", "RESPONSE_SYNTHESIS", "RECOVERY", "FINALIZE"];
const ACTION_STATUSES: readonly ActionStatus[] = ["PROPOSED", "MODIFIED", "APPROVED", "REJECTED", "EXPIRED", "EXECUTING", "UNKNOWN_RESULT", "EXECUTED", "VERIFIED", "FAILED", "BLOCKED", "DEPENDENCY_BLOCKED", "MISMATCH", "CANCELLED"];
const RECOVERY_REASONS = ["UNKNOWN_RESULT", "VERIFICATION_MISMATCH", "CHECKPOINT_MISMATCH", "CONTRACT_VIOLATION"] as const;
const RECOVERY_RESOLUTIONS: readonly RecoveryResolution[] = ["RECHECK", "ACCEPT_PARTIAL", "CREATE_CORRECTIVE_PLAN", "CANCEL", "FAIL"];
const TERMINAL_STATUSES = ["COMPLETED", "BLOCKED", "FAILED", "CANCELLED"] as const;
const RESULT_KINDS = ["SUCCESS", "PARTIAL", "BLOCKED", "FAILED", "CANCELLED"] as const;

export class RunSseContractError extends Error {}

export function decodeRunSseEvent(data: string): RunSseEvent {
  let raw: unknown;
  try {
    raw = JSON.parse(data) as unknown;
  } catch {
    throw new RunSseContractError("SSE data is not valid JSON");
  }
  if (!isRecord(raw) || !hasExactKeys(raw, ["schema_version", "event_id", "run_id", "action_id", "occurred_at_ms", "event_type", "payload", "projection_version"])) throw new RunSseContractError("SSE envelope fields are invalid");
  if (raw.schema_version !== 1 || !isString(raw.event_id) || !isString(raw.run_id) || !(raw.action_id === null || isString(raw.action_id)) || !isInteger(raw.occurred_at_ms) || !isInteger(raw.projection_version) || !isEventType(raw.event_type)) throw new RunSseContractError("SSE envelope values are invalid");
  validatePayload(raw.event_type, raw.payload);
  return raw as RunSseEvent;
}

function validatePayload(eventType: RunSseEventType, raw: unknown): void {
  if (!isRecord(raw)) throw new RunSseContractError(`${eventType} payload must be an object`);
  switch (eventType) {
    case "run_status": requireShape(raw, ["status", "snapshot_version"], isOneOf(raw.status, RUN_STATUSES) && isInteger(raw.snapshot_version)); return;
    case "phase_changed": requireShape(raw, ["phase"], isOneOf(raw.phase, WORKFLOW_PHASES)); return;
    case "tool_routing": requireShape(raw, ["route_revision", "input_route_count", "output_mode"], isInteger(raw.route_revision) && isInteger(raw.input_route_count) && isOneOf(raw.output_mode, ["ANSWER", "ACTION"])); return;
    case "retrieval_progress": requireShape(raw, ["coverage", "completed_sources", "total_sources"], isOneOf(raw.coverage, ["NONE", "PARTIAL", "SUFFICIENT"]) && isInteger(raw.completed_sources) && isInteger(raw.total_sources)); return;
    case "confirmation_required": requireShape(raw, ["interrupt_id", "question", "options"], isString(raw.interrupt_id) && isString(raw.question) && isStringArray(raw.options)); return;
    case "analysis_progress": requireShape(raw, ["completed_stage"], isString(raw.completed_stage)); return;
    case "plan_updated": requireShape(raw, ["plan_id", "revision_no"], (raw.plan_id === null || isString(raw.plan_id)) && isInteger(raw.revision_no)); return;
    case "approval_required": requireShape(raw, ["action_ids"], isStringArray(raw.action_ids)); return;
    case "action_status": requireShape(raw, ["action_id", "status"], isString(raw.action_id) && isOneOf(raw.status, ACTION_STATUSES)); return;
    case "verification_result": requireShape(raw, ["action_id", "outcome"], isString(raw.action_id) && isOneOf(raw.outcome, ["VERIFIED", "MISMATCH"])); return;
    case "reauth_required": requireShape(raw, ["connector_id"], isString(raw.connector_id)); return;
    case "recovery_required": validateRecovery(raw); return;
    case "completed": requireShape(raw, ["status", "result_kind"], isOneOf(raw.status, TERMINAL_STATUSES) && isOneOf(raw.result_kind, RESULT_KINDS)); return;
    case "error": requireShape(raw, ["error_code", "recoverable"], isString(raw.error_code) && typeof raw.recoverable === "boolean"); return;
    default: assertNever(eventType);
  }
}

function validateRecovery(raw: Record<string, unknown>): void {
  if (!hasExactKeys(raw, ["recovery"]) || !isRecord(raw.recovery)) throw new RunSseContractError("recovery_required payload is invalid");
  const recovery = raw.recovery;
  if (!hasExactKeys(recovery, ["reason_code", "target", "allowed_resolution_kinds"]) || !isOneOf(recovery.reason_code, RECOVERY_REASONS) || !isOneOfArray(recovery.allowed_resolution_kinds, RECOVERY_RESOLUTIONS) || !isRecord(recovery.target)) throw new RunSseContractError("recovery projection is invalid");
  const target = recovery.target;
  const validTarget = target.target_kind === "RUN"
    ? hasExactKeys(target, ["target_kind"])
    : target.target_kind === "ACTION" && hasExactKeys(target, ["target_kind", "action_id"]) && isString(target.action_id);
  if (!validTarget) throw new RunSseContractError("recovery target is invalid");
}

function requireShape(raw: Record<string, unknown>, keys: readonly string[], valid: boolean): void {
  if (!hasExactKeys(raw, keys) || !valid) throw new RunSseContractError("SSE payload fields are invalid");
}

function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
function isString(value: unknown): value is string { return typeof value === "string"; }
function isInteger(value: unknown): value is number { return typeof value === "number" && Number.isInteger(value); }
function isStringArray(value: unknown): value is string[] { return Array.isArray(value) && value.every(isString); }
function isOneOf<T extends string>(value: unknown, allowed: readonly T[]): value is T { return typeof value === "string" && allowed.includes(value as T); }
function isOneOfArray<T extends string>(value: unknown, allowed: readonly T[]): value is T[] { return Array.isArray(value) && value.every((item) => isOneOf(item, allowed)); }
function isEventType(value: unknown): value is RunSseEventType { return isOneOf(value, RUN_SSE_EVENT_TYPES); }
function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean { const actual = Object.keys(value); return actual.length === keys.length && keys.every((key) => Object.hasOwn(value, key)); }
function assertNever(value: never): never { throw new RunSseContractError(`unsupported SSE event: ${String(value)}`); }
