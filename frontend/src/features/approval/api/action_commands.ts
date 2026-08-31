import { API_CONTRACT_VERSION, type ActionCommandResponse } from "../../../api/contract";
import { requestJson } from "../../../api/client";

export function approveAction(payload: { action_id: string; command_id: string; expected_version: number; duplicate_acknowledged?: boolean; calendar_conflict_acknowledged?: boolean }): Promise<ActionCommandResponse> {
  return requestJson(`/api/v1/actions/${encodeURIComponent(payload.action_id)}/approve`, { method: "POST", body: { command_id: payload.command_id, expected_version: payload.expected_version, duplicate_acknowledged: payload.duplicate_acknowledged ?? false, calendar_conflict_acknowledged: payload.calendar_conflict_acknowledged ?? false, api_contract_version: API_CONTRACT_VERSION } });
}

export function rejectAction(payload: { action_id: string; command_id: string; expected_version: number; reason_code?: string }): Promise<ActionCommandResponse> {
  return requestJson(`/api/v1/actions/${encodeURIComponent(payload.action_id)}/reject`, { method: "POST", body: { command_id: payload.command_id, expected_version: payload.expected_version, reason_code: payload.reason_code ?? null, api_contract_version: API_CONTRACT_VERSION } });
}

export function modifyAction(payload: { action_id: string; command_id: string; expected_version: number; arguments_patch?: Record<string, unknown> }): Promise<ActionCommandResponse> {
  return requestJson(`/api/v1/actions/${encodeURIComponent(payload.action_id)}/modify`, { method: "POST", body: { command_id: payload.command_id, expected_version: payload.expected_version, arguments_patch: payload.arguments_patch ?? {}, api_contract_version: API_CONTRACT_VERSION } });
}

export function prepareRetry(payload: { action_id: string; command_id: string; expected_version: number }): Promise<ActionCommandResponse> {
  return requestJson(`/api/v1/actions/${encodeURIComponent(payload.action_id)}/prepare-retry`, { method: "POST", body: { command_id: payload.command_id, expected_version: payload.expected_version, api_contract_version: API_CONTRACT_VERSION } });
}
