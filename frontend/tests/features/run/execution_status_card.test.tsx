import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import type { RunSnapshot } from "../../../src/api/contract";
import { ExecutionStatusCard } from "../../../src/features/run/execution_status_card";

test.each([["gmail_send", "메일"], ["tasks_create_task", "태스크"], ["calendar_create_event", "캘린더"]])("ExecutionStatusCard keeps %s UNKNOWN_RESULT non-terminal in Korean", (toolName, label) => {
  const snapshot = { actions: [{ action_id: "a-1", tool_name: toolName, status: "UNKNOWN_RESULT", delivery_certainty: "SENT_RESPONSE_LOST" }], verification_summary: { verified_count: 0, mismatch_count: 0 }, recovery_summary: { unknown_result_action_count: 1 } } as RunSnapshot;
  render(<ExecutionStatusCard snapshot={snapshot} />);
  expect(screen.getByText(`${label} 실행 에이전트 · 응답을 받지 못해 실제 결과를 안전하게 확인하고 있습니다.`)).toBeInTheDocument();
  expect(screen.getByText("결과 불명 작업 1건을 확인하고 있습니다.")).toBeInTheDocument();
  expect(document.body.textContent).not.toContain("SENT_RESPONSE_LOST");
  expect(document.body.textContent).not.toContain("실행 및 검증 상태");
  expect(document.body.textContent).not.toContain("성공했습니다");
});
