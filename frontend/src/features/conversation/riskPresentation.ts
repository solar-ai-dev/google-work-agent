export type TaskDuplicateDecision =
  | "NOT_DUPLICATE"
  | "SIMILAR_CANDIDATE"
  | "CLEAR_DUPLICATE";

export function taskDuplicateDecision(risk: Record<string, unknown>): TaskDuplicateDecision | null {
  const duplicate = risk.duplicate;
  if (!duplicate || typeof duplicate !== "object") return null;
  const decision = (duplicate as { decision?: unknown }).decision;
  return decision === "NOT_DUPLICATE" || decision === "SIMILAR_CANDIDATE" || decision === "CLEAR_DUPLICATE" ? decision : null;
}

export type CalendarConflictDecision = "NO_CONFLICT" | "WARNING" | "HARD_CONFLICT";

export function calendarConflictDecision(risk: Record<string, unknown>): CalendarConflictDecision | null {
  const conflict = risk.calendar_conflict;
  if (!conflict || typeof conflict !== "object") return null;
  const decision = (conflict as { decision?: unknown }).decision;
  return decision === "NO_CONFLICT" || decision === "WARNING" || decision === "HARD_CONFLICT" ? decision : null;
}

export type FeasibilityDecision = "FEASIBLE" | "RISK" | "INFEASIBLE";

export function feasibilityDecision(risk: Record<string, unknown>): FeasibilityDecision | null {
  const feasibility = risk.feasibility;
  if (!feasibility || typeof feasibility !== "object") return null;
  const decision = (feasibility as { decision?: unknown }).decision;
  return decision === "FEASIBLE" || decision === "RISK" || decision === "INFEASIBLE" ? decision : null;
}

export function hasOtherRisk(risk: Record<string, unknown>): boolean {
  return Object.keys(risk).some((key) => key !== "duplicate" && key !== "calendar_conflict" && key !== "feasibility" && key !== "feasibility_input");
}
