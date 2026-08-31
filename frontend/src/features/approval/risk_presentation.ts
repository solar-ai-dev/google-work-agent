export type TaskDuplicateDecision = "NOT_DUPLICATE" | "SIMILAR_CANDIDATE" | "CLEAR_DUPLICATE";

export function taskDuplicateDecision(risk: Record<string, unknown>): TaskDuplicateDecision | null {
  const value = risk.duplicate;
  const decision = value && typeof value === "object" ? (value as { decision?: unknown }).decision : null;
  return decision === "NOT_DUPLICATE" || decision === "SIMILAR_CANDIDATE" || decision === "CLEAR_DUPLICATE" ? decision : null;
}

export type CalendarConflictDecision = "NO_CONFLICT" | "WARNING" | "HARD_CONFLICT";

export function calendarConflictDecision(risk: Record<string, unknown>): CalendarConflictDecision | null {
  const value = risk.calendar_conflict;
  const decision = value && typeof value === "object" ? (value as { decision?: unknown }).decision : null;
  return decision === "NO_CONFLICT" || decision === "WARNING" || decision === "HARD_CONFLICT" ? decision : null;
}

export type FeasibilityDecision = "FEASIBLE" | "RISK" | "INFEASIBLE";

export function feasibilityDecision(risk: Record<string, unknown>): FeasibilityDecision | null {
  const value = risk.feasibility;
  const decision = value && typeof value === "object" ? (value as { decision?: unknown }).decision : null;
  return decision === "FEASIBLE" || decision === "RISK" || decision === "INFEASIBLE" ? decision : null;
}

export function hasOtherRisk(risk: Record<string, unknown>): boolean {
  return Object.keys(risk).some((key) => !["duplicate", "calendar_conflict", "feasibility", "feasibility_input"].includes(key));
}
