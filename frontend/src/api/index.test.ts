import { describe, expect, test, vi } from "vitest";
import * as api from "./index";

describe("api index wrappers", () => {
  test("calls same-origin endpoints with the expected methods", async () => {
    globalThis.fetch = vi.fn(async () =>
      new Response(JSON.stringify({}), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ) as typeof fetch;

    const cases: Array<{
      call: () => Promise<unknown>;
      path: string;
      method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
      bodyIncludes?: Record<string, unknown>;
      formIncludes?: Record<string, string>;
    }> = [
      { call: () => api.getLive(), path: "/health/live", method: "GET" },
      { call: () => api.getReady(), path: "/health/ready", method: "GET" },
      {
        call: () =>
          api.bootstrapSession({
            bootstrap_secret: "secret-1",
          }),
        path: "/api/v1/session/bootstrap",
        method: "POST",
        bodyIncludes: {
          schema_version: 1,
          bootstrap_secret: "secret-1",
          frontend_api_contract_version: "1",
        },
      },
      { call: () => api.getRuntime(), path: "/api/v1/runtime", method: "GET" },
      { call: () => api.getSettings(), path: "/api/v1/settings", method: "GET" },
      { call: () => api.getLLMConnection(), path: "/api/v1/credentials/llm/gemini", method: "GET" },
      {
        call: () =>
          api.patchSettings({
            command_id: "settings-1",
            preferred_llm_mode: "AUTO",
            external_llm_consent: true,
          }),
        path: "/api/v1/settings",
        method: "PUT",
        bodyIncludes: { command_id: "settings-1" },
      },
      {
        call: () =>
          api.storeLLMApiKey({
            api_key: "sk-test",
            storage_mode: "KEYRING",
          }),
        path: "/api/v1/credentials/llm/gemini",
        method: "PUT",
        bodyIncludes: { api_key: "sk-test", storage_mode: "KEYRING" },
      },
      { call: () => api.deleteLLMApiKey(), path: "/api/v1/credentials/llm/gemini", method: "DELETE" },
      { call: () => api.getGoogleConnection(), path: "/api/v1/connections/google/status", method: "GET" },
      { call: () => api.startGoogleOAuth(), path: "/api/v1/connections/google/start", method: "POST" },
      { call: () => api.disconnectGoogle(), path: "/api/v1/connections/google/disconnect", method: "POST" },
      {
        call: () => api.getCurrentAccount(),
        path: "/api/v1/identity/google-account",
        method: "GET",
      },
      { call: () => api.getRunSnapshot("run-1"), path: "/api/v1/runs/run-1", method: "GET" },
      {
        call: () => api.getRunContext("run-1"),
        path: "/api/v1/runs/run-1/context",
        method: "GET",
      },
      {
        call: () =>
          api.cancelRun({
            run_id: "run-1",
            command_id: "command-3",
            expected_version: 4,
          }),
        path: "/api/v1/runs/run-1/cancel",
        method: "POST",
        bodyIncludes: { expected_version: 4 },
      },
      {
        call: () =>
          api.resumeRun({
            run_id: "run-1",
            command_id: "command-4",
            expected_version: 4,
            resume_kind: "RECOVERY_RECHECK",
          }),
        path: "/api/v1/runs/run-1/resume",
        method: "POST",
        bodyIncludes: { expected_version: 4, resume_kind: "RECOVERY_RECHECK" },
      },
      {
        call: () =>
          api.confirmRun({
            run_id: "run-1",
            command_id: "command-confirm",
            expected_version: 4,
            interrupt_id: "interrupt-1",
            response_kind: "OPTION",
            selected_option: "option-1",
          }),
        path: "/api/v1/runs/run-1/confirm",
        method: "POST",
        bodyIncludes: { interrupt_id: "interrupt-1", selected_option: "option-1" },
      },
      {
        call: () =>
          api.resolveRecovery({
            run_id: "run-1",
            command_id: "command-recovery",
            expected_version: 4,
            action_id: "action-1",
            resolution_kind: "ACCEPT_PARTIAL",
          }),
        path: "/api/v1/runs/run-1/resolve-recovery",
        method: "POST",
        bodyIncludes: { action_id: "action-1", resolution_kind: "ACCEPT_PARTIAL" },
      },
      {
        call: () =>
          api.approveAction({
            action_id: "action-1",
            command_id: "command-5",
            expected_version: 2,
          }),
        path: "/api/v1/actions/action-1/approve",
        method: "POST",
        bodyIncludes: { expected_version: 2 },
      },
      {
        call: () =>
          api.rejectAction({
            action_id: "action-1",
            command_id: "command-6",
            expected_version: 2,
          }),
        path: "/api/v1/actions/action-1/reject",
        method: "POST",
        bodyIncludes: { expected_version: 2 },
      },
      {
        call: () =>
          api.modifyAction({
            action_id: "action-1",
            command_id: "command-7",
            expected_version: 2,
            arguments_patch: { subject: "Updated" },
          }),
        path: "/api/v1/actions/action-1/modify",
        method: "POST",
        bodyIncludes: { expected_version: 2, arguments_patch: { subject: "Updated" } },
      },
      {
        call: () =>
          api.prepareRetry({
            action_id: "action-1",
            command_id: "command-8",
            expected_version: 3,
          }),
        path: "/api/v1/actions/action-1/prepare-retry",
        method: "POST",
        bodyIncludes: { expected_version: 3 },
      },
      {
        call: () => api.stageAttachment(new File(["abc"], "a.txt", { type: "text/plain" })),
        path: "/api/v1/attachments/stage",
        method: "POST",
        formIncludes: { filename: "a.txt", mime_type: "text/plain" },
      },
    ];

    for (const testCase of cases) {
      await testCase.call();
      const [path, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.at(-1) as [
        string,
        RequestInit,
      ];
      expect(path).toBe(testCase.path);
      expect(init.method).toBe(testCase.method);
      if (testCase.bodyIncludes) {
        expect(JSON.parse(String(init.body))).toEqual(expect.objectContaining(testCase.bodyIncludes));
      }
      if (testCase.formIncludes) {
        expect(init.body).toBeInstanceOf(FormData);
        const form = init.body as FormData;
        const file = form.get("file") as File;
        expect(file.name).toBe(testCase.formIncludes.filename);
        expect(file.type).toBe(testCase.formIncludes.mime_type);
        expect(form.get("command_id")).toEqual(expect.any(String));
        expect((init.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
      }
    }
  });
});
