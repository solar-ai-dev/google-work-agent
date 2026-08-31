import { requestJson } from "../../../api/client";
import type { ConversationHistoryResponse, ConversationListResponse } from "../../../api/contract";

export function listConversations(cursor?: string | null, query?: string | null): Promise<ConversationListResponse> {
  const search = new URLSearchParams({ page_size: "50" });
  if (cursor) search.set("cursor", cursor);
  if (query) search.set("search", query);
  return requestJson(`/api/v1/conversations?${search.toString()}`);
}

export function getConversationHistory(conversationId: string): Promise<ConversationHistoryResponse> {
  return requestJson(`/api/v1/conversations/${encodeURIComponent(conversationId)}/history`);
}
