import type { RunContextResponse, RunSnapshot } from "../../../api/contract";
import { requestJson } from "../../../api/client";

export function getRunSnapshot(runId: string): Promise<RunSnapshot> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(runId)}`);
}

export function getRunContext(runId: string): Promise<RunContextResponse> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(runId)}/context`);
}
