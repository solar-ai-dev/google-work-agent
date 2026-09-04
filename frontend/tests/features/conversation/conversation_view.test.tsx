import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import type { ConversationMessage, RunSnapshot } from "../../../src/api/contract";
import {
  ConversationView,
  type ConversationViewModel,
} from "../../../src/features/conversation/ConversationView";

const finalMessage: ConversationMessage = {
  schema_version: 1,
  id: "message-final",
  run_id: "run-1",
  role: "ASSISTANT",
  content: "요청하신 태스크를 만들고 Google에서 결과를 확인했습니다.",
  created_at_ms: 2,
};

test("terminal snapshot message appears immediately and is deduplicated from history", () => {
  const snapshot = {
    run: {
      run_id: "run-1",
      conversation_id: "conversation-1",
      status: "COMPLETED",
      version: 2,
      entry_mode: "AGENT_SEARCH",
      requested_mode: "AUTO",
      actual_runtime: "LOCAL_GPU",
      started_at_ms: 1,
      finished_at_ms: 2,
      next_allowed_commands: [],
    },
    messages: [finalMessage],
    current_plan: null,
    actions: [],
    context_preview: null,
    approvals: [],
    execution_status: { action_count: 0, terminal_action_count: 0 },
    verification_summary: { verified_count: 0, mismatch_count: 0 },
    recovery_summary: { unknown_result_action_count: 0 },
    pending_interrupt: null,
    recovery: null,
    error: null,
    external_llm_transfer_scope: null,
    terminal_result_kind: "SUCCESS",
    projection_version: 1,
  } satisfies RunSnapshot;
  const viewModel = {
    controller: {
      selectedConversationId: "conversation-1",
      historyMessages: [{ ...finalMessage, content: "stale history copy" }],
      runSnapshot: snapshot,
      runContext: null,
      latestRunEvent: null,
      confirmationText: "",
      setConfirmationText: vi.fn(),
      composerText: "",
      composerError: null,
      setComposerText: vi.fn(),
      setComposerError: vi.fn(),
      busyCommand: null,
      handleStartRun: vi.fn(),
      handleApprove: vi.fn(),
      handleSimpleAction: vi.fn(),
      handleAttachDescriptors: vi.fn(),
      handleCancelRun: vi.fn(),
      handleResumeRun: vi.fn(),
      handleAdjustContext: vi.fn(),
      handleConfirmation: vi.fn(),
      handleResolveRecovery: vi.fn(),
    },
    resourceContext: { selectedResourceIds: [], selectedResourceLabels: [], composerPrompt: "" },
    formatTime: (value: number) => String(value),
    onOpenSettings: vi.fn(),
    onOpenDiagnostics: vi.fn(),
  } satisfies ConversationViewModel;

  render(<ConversationView viewModel={viewModel}><div /></ConversationView>);

  expect(screen.getAllByText(finalMessage.content)).toHaveLength(1);
  expect(screen.queryByText("stale history copy")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("에이전트 진행")).not.toBeInTheDocument();
});
