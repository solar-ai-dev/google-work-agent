import { requestJson } from "../../../api/client";
import type { GmailResourceDetailResponse } from "../../../api/contract";

export function getGmailResourceDetail(resourceId: string): Promise<GmailResourceDetailResponse> {
  return requestJson(`/api/v1/resources/gmail/${encodeURIComponent(resourceId)}`);
}
