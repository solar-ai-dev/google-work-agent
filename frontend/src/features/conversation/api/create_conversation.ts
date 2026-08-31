import { requestJson } from "../../../api/client";
import type { ConversationItem } from "../../../api/contract";

export function createConversation(payload: {
  command_id: string;
  title: string | null;
}): Promise<ConversationItem> {
  return requestJson("/api/v1/conversations", {
    method: "POST",
    body: { schema_version: 1, ...payload },
  });
}
