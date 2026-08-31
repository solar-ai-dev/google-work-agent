import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { RunSnapshot } from "../../../src/api/contract";
import { RunProgress } from "../../../src/features/run/run_progress";

test("RunProgress exposes only server-projected cancel and resume actions", async () => {
  const snapshot = { run: { status: "BLOCKED", next_allowed_commands: ["REQUEST_CANCEL"] }, execution_status: { action_count: 1, terminal_action_count: 0 }, terminal_result_kind: "NONE", error: { actions: [{ kind: "RESUME_SAFE_CHECKPOINT", resume_kind: "SAFE_CHECKPOINT_RESUME" }] } } as RunSnapshot;
  const onResume = vi.fn();
  render(<RunProgress snapshot={snapshot} busy={null} onCancel={vi.fn()} onResume={onResume} />);
  await userEvent.setup().click(screen.getByRole("button", { name: "재개" }));
  expect(onResume).toHaveBeenCalledWith("SAFE_CHECKPOINT_RESUME");
});
