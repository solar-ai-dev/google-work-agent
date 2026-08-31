import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { ConversationHistoryPanel } from "../../../src/features/conversation/conversation_history_panel";

test("ConversationHistoryPanel filters stored server history and selects its conversation identity", () => {
  const select = vi.fn();
  render(<ConversationHistoryPanel conversations={[
    { schema_version: 1, conversation_id: "conversation-1", title: "예산 검토", latest_message_at_ms: null, open_run_id: null },
    { schema_version: 1, conversation_id: "conversation-2", title: "일정 조정", latest_message_at_ms: null, open_run_id: null },
  ]} selectedConversationId={null} hasRunSnapshot={false} onBeginConversation={vi.fn()} onSelectConversation={select} />);
  fireEvent.change(screen.getByRole("textbox", { name: "대화 검색" }), { target: { value: "예산" } });
  expect(screen.getByText("예산 검토")).toBeInTheDocument();
  expect(screen.queryByText("일정 조정")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /예산 검토/ }));
  expect(select).toHaveBeenCalledWith("conversation-1");
});
