import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { AttachmentList } from "../../../src/features/attachment/attachment_list";

test("AttachmentList delegates opaque identifiers without trusting the displayed filename", async () => {
  const onDownload = vi.fn();
  render(<AttachmentList attachments={[{ message_id: "m-1", attachment_id: "a-1", filename: "shown.txt", mime_type: "text/plain", size_bytes: 12 }]} onDownload={onDownload} />);
  await userEvent.setup().click(screen.getByRole("button", { name: "shown.txt" }));
  expect(onDownload).toHaveBeenCalledWith("m-1", "a-1");
});
