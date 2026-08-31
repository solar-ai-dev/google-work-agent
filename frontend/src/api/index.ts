import {
  API_CONTRACT_VERSION,
  type BootstrapResponse,
  type LiveResponse,
  type ReadyResponse,
} from "./contract";
import { requestJson } from "./client";

export function getLive(): Promise<LiveResponse> {
  return requestJson("/health/live");
}

export function getReady(): Promise<ReadyResponse> {
  return requestJson("/health/ready");
}

export function bootstrapSession(payload: {
  bootstrap_secret: string;
}): Promise<BootstrapResponse> {
  return requestJson("/api/v1/session/bootstrap", {
    method: "POST",
    body: {
      schema_version: 1,
      bootstrap_secret: payload.bootstrap_secret,
      frontend_api_contract_version: API_CONTRACT_VERSION,
    },
  });
}
