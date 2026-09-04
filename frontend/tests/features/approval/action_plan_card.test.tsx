import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { RunSnapshot } from "../../../src/api/contract";
import { ActionPlanCard } from "../../../src/features/approval/action_plan_card";

test("ActionPlanCard presents user-facing arguments and sends only explicit acknowledgement", async () => {
  const action = { action_id: "a-1", tool_name: "tasks_create_task", arguments: { task_list_id: "@default", payload: { title: "분기 보고서 제출", scheduled_date: "2026-09-05" } }, status: "PROPOSED", version: 1, effect_type: "CREATE", approval_required: true, verification_policy: "GET_COMPARE", risk: { duplicate: { decision: "SIMILAR_CANDIDATE", matched_resource_ids: ["private"] } }, next_allowed_commands: ["APPROVE_ACTION"], required_acknowledgements: ["TASK_DUPLICATE"], editable_fields: [], attachment_allowed: false } as const;
  const snapshot = { current_plan: { summary_text: "계획" }, actions: [action], approvals: [] } as unknown as RunSnapshot;
  const onApprove = vi.fn();
  render(<ActionPlanCard snapshot={snapshot} busy={null} retryActionIds={new Set()} formatTime={String} onApprove={onApprove} onModify={vi.fn()} onReject={vi.fn()} onRetry={vi.fn()} onAttachDescriptors={vi.fn()} />);
  const user = userEvent.setup();
  const approve = screen.getByRole("button", { name: "위험을 확인하고 실행해 주세요" });
  expect(screen.queryByText("Action Plan")).not.toBeInTheDocument();
  expect(screen.getByText("분기 보고서 제출")).toBeInTheDocument();
  expect(screen.getByText("내 할 일 목록")).toBeInTheDocument();
  expect(screen.getByText("2026-09-05")).toBeInTheDocument();
  expect(screen.queryByText("@default")).not.toBeInTheDocument();
  expect(screen.queryByText("tasks_create_task")).not.toBeInTheDocument();
  expect(approve).toBeDisabled();
  await user.click(screen.getByRole("checkbox", { name: "중복 가능성을 확인했습니다." }));
  expect(approve).toBeEnabled();
  await user.click(approve);
  expect([...onApprove.mock.calls[0][1]]).toEqual(["TASK_DUPLICATE"]);
  expect(document.body.textContent).not.toContain("private");
});
