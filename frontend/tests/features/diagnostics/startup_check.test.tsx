import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { StartupCheckScreen } from "../../../src/features/diagnostics/startup_check";

test("shows readiness evidence and exposes retry only after failure", async () => {
  const retry = vi.fn();
  render(<StartupCheckScreen state={{ phase: "readiness", status: "error", message: "준비 실패", checks: [{ name: "sqlite", state: "NOT_READY", detail: "migration" }], error: "확인 필요" }} onRetry={retry} />);

  expect(screen.getByText("sqlite")).toBeInTheDocument();
  expect(screen.getByText("migration")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "다시 확인" }));
  expect(retry).toHaveBeenCalledOnce();
});
