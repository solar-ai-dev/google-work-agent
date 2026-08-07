import { describe, expect, test, vi } from "vitest";
import { requestJson } from "./client";

describe("requestJson", () => {
  test("parses a same-origin JSON response", async () => {
    globalThis.fetch = vi.fn(async () =>
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ) as typeof fetch;

    await expect(requestJson<{ ok: boolean }>("/api/v1/runtime")).resolves.toEqual({ ok: true });
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/runtime",
      expect.objectContaining({ credentials: "same-origin", method: "GET" }),
    );
  });

  test("rejects non same-origin paths before fetch", async () => {
    await expect(requestJson("https://example.com/api")).rejects.toThrow(
      "same-origin relative path is required",
    );
  });

  test("maps JSON error envelopes to ApiClientError", async () => {
    globalThis.fetch = vi.fn(async () =>
      new Response(
        JSON.stringify({
          error_code: "SESSION_INVALID",
          user_message: "세션이 만료되었습니다.",
          retryable: false,
          request_id: "req-1",
          api_contract_version: "1",
        }),
        {
          status: 401,
          headers: { "Content-Type": "application/json" },
        },
      ),
    ) as typeof fetch;

    await expect(requestJson("/api/v1/runtime")).rejects.toMatchObject({
      name: "ApiClientError",
      status: 401,
      message: "세션이 만료되었습니다.",
    });
  });

  test("returns a safe error for unexpected non-json responses", async () => {
    globalThis.fetch = vi.fn(async () =>
      new Response("<html>bad gateway</html>", {
        status: 200,
        headers: { "Content-Type": "text/html" },
      }),
    ) as typeof fetch;

    await expect(requestJson("/api/v1/runtime")).rejects.toMatchObject({
      name: "ApiClientError",
      status: 200,
      message: "예상하지 못한 응답 형식입니다.",
    });
  });
});
