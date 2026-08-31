import { expect, test, vi } from "vitest";
import { downloadAttachment } from "../../../../src/features/attachment/api/download_attachment";

test("downloadAttachment uses the server Content-Disposition filename and revokes the object URL", async () => {
  const payload = new Blob(["abc"]);
  globalThis.fetch = vi.fn().mockResolvedValue(new Response(payload, { status: 200, headers: { "Content-Disposition": 'attachment; filename="attachment"' } }));
  const create = vi.fn().mockReturnValue("blob:test");
  const revoke = vi.fn();
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: create });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revoke });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  await downloadAttachment("m/1", "a/1");
  expect(globalThis.fetch).toHaveBeenCalledWith("/api/v1/gmail/messages/m%2F1/attachments/a%2F1", expect.any(Object));
  expect(click).toHaveBeenCalledOnce();
  expect(create).toHaveBeenCalledOnce();
  expect(revoke).toHaveBeenCalledWith("blob:test");
});
