import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { RunSnapshot } from "../../../src/api/contract";
import { RecoveryCard } from "../../../src/features/recovery/recovery_card";

test("RecoveryCard renders only projected resolution kinds", async () => {
  const snapshot = { recovery: { reason_code: "UNKNOWN_RESULT", message: "실제 Google 결과를 먼저 확인해야 합니다.", target: { target_kind: "ACTION", action_id: "a-1" }, allowed_resolution_kinds: ["RECHECK"] }, error: null } as RunSnapshot;
  const onResolve = vi.fn();
  render(<RecoveryCard snapshot={snapshot} busy={null} onResolve={onResolve} />);
  expect(screen.getByText("실제 Google 결과를 먼저 확인해야 합니다.")).toBeInTheDocument();
  expect(screen.queryByText("UNKNOWN_RESULT")).not.toBeInTheDocument();
  await userEvent.setup().click(screen.getByRole("button", { name: "다시 확인" }));
  expect(onResolve).toHaveBeenCalledWith("RECHECK");
  expect(screen.queryByRole("button", { name: "현재 결과 수용" })).not.toBeInTheDocument();
});

test("RecoveryCard hides a stale resume-only error while a run is active", () => {
  const snapshot = {
    run: { status: "ANALYZING" },
    recovery: null,
    error: {
      message: "This run can continue from its validated safe checkpoint.",
      actions: [
        { kind: "RESUME_SAFE_CHECKPOINT", resume_kind: "SAFE_CHECKPOINT_RESUME" },
        { kind: "OPEN_DIAGNOSTICS" },
      ],
    },
  } as RunSnapshot;
  const { container } = render(
    <RecoveryCard snapshot={snapshot} busy={null} onResolve={vi.fn()} />,
  );
  expect(container).toBeEmptyDOMElement();
});
