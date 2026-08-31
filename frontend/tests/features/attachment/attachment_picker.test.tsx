import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { AttachmentPicker, MAX_ATTACHMENT_BYTES } from "../../../src/features/attachment/attachment_picker";
import * as api from "../../../src/features/attachment/api/stage_attachment";

vi.mock("../../../src/features/attachment/api/stage_attachment", () => ({ stageAttachment: vi.fn() }));

test("AttachmentPicker rejects oversized files before staging", async () => {
  render(<AttachmentPicker disabled={false} onStaged={vi.fn()} />);
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  await userEvent.setup().upload(input, new File([new Uint8Array(MAX_ATTACHMENT_BYTES + 1)], "large.bin", { type: "application/octet-stream" }));
  expect(api.stageAttachment).not.toHaveBeenCalled();
  expect(await screen.findByRole("status")).toHaveTextContent("8 MB");
});
