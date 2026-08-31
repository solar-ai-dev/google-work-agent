import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { RunSnapshot } from "../../../src/api/contract";
import { ActionPlanCard } from "../../../src/features/approval/action_plan_card";

test("ActionPlanCard sends only explicit server-projected acknowledgement", async () => {
  const action = { action_id: "a-1", tool_name: "tasks_create_task", status: "PROPOSED", version: 1, effect_type: "CREATE", approval_required: true, verification_policy: "GET_COMPARE", risk: { duplicate: { decision: "SIMILAR_CANDIDATE", matched_resource_ids: ["private"] } }, next_allowed_commands: ["APPROVE_ACTION"], required_acknowledgements: ["TASK_DUPLICATE"], editable_fields: [], attachment_allowed: false } as const;
  const snapshot = { current_plan: { summary_text: "계획" }, actions: [action], approvals: [] } as unknown as RunSnapshot;
  const onApprove = vi.fn();
  render(<ActionPlanCard snapshot={snapshot} busy={null} retryActionIds={new Set()} formatTime={String} onApprove={onApprove} onModify={vi.fn()} onReject={vi.fn()} onRetry={vi.fn()} onAttachFiles={vi.fn()} />);
  await userEvent.setup().click(screen.getByRole("button", { name: "확인하고 승인" }));
  expect([...onApprove.mock.calls[0][1]]).toEqual(["TASK_DUPLICATE"]);
  expect(document.body.textContent).not.toContain("private");
});
