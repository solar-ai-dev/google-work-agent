import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { RunSnapshot } from "../../../src/api/contract";
import { RecoveryCard } from "../../../src/features/recovery/recovery_card";

test("RecoveryCard renders only projected resolution kinds", async () => {
  const snapshot = { recovery: { reason_code: "UNKNOWN_RESULT", target: { target_kind: "ACTION", action_id: "a-1" }, allowed_resolution_kinds: ["RECHECK"] }, error: null } as RunSnapshot;
  const onResolve = vi.fn();
  render(<RecoveryCard snapshot={snapshot} busy={null} onResolve={onResolve} />);
  await userEvent.setup().click(screen.getByRole("button", { name: "다시 확인" }));
  expect(onResolve).toHaveBeenCalledWith("RECHECK");
  expect(screen.queryByRole("button", { name: "현재 결과 수용" })).not.toBeInTheDocument();
});
