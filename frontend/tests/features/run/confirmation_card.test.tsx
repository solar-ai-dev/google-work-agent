import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ConfirmationCard } from "../../../src/features/run/confirmation_card";

test("ConfirmationCard submits only one projected option", async () => {
  const onSubmit = vi.fn();
  render(<ConfirmationCard interrupt={{ schema_version: 1, interrupt_id: "i-1", semantic_owner_id: "PLANNING", question: "선택하세요", options: ["A", "B"], response_mode: "OPTION" }} text="" busy={false} onTextChange={vi.fn()} onSubmit={onSubmit} />);
  await userEvent.setup().click(screen.getByRole("button", { name: "A" }));
  expect(onSubmit).toHaveBeenCalledWith("A");
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
});
