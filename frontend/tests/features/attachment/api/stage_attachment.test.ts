import { expect, test, vi } from "vitest";
import { stageAttachment } from "../../../../src/features/attachment/api/stage_attachment";

test("stageAttachment sends caller-owned stable identity and preserves expiry", async () => {
  globalThis.fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ staged_attachment_id: "s-1", filename: "a.txt", mime_type: "text/plain", size_bytes: 3, sha256: "a".repeat(64), expires_at_ms: 99, api_contract_version: "1" }), { status: 200, headers: { "Content-Type": "application/json" } }));
  const result = await stageAttachment(new File(["abc"], "a.txt", { type: "text/plain" }), "command-stable");
  const init = vi.mocked(globalThis.fetch).mock.calls[0][1]!;
  expect((init.body as FormData).get("command_id")).toBe("command-stable");
  expect(result.expires_at_ms).toBe(99);
});
