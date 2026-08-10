import { render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App } from "./App";

type MockResponse = {
  status?: number;
  json?: unknown;
  headers?: Record<string, string>;
};

type SnapshotShape = {
  run_id: string;
  conversation_id: string;
  status: string;
  version: number;
  entry_mode: string;
  requested_mode: string;
  actual_runtime: string;
  started_at_ms: number;
  finished_at_ms: number | null;
  active_plan: {
    plan_id: string;
    revision_no: number;
    status: string;
    summary_text: string;
    created_at_ms: number;
  };
  actions: Array<{
    action_id: string;
    tool_name: string;
    status: string;
    version: number;
    effect_type: string;
    approval_required: boolean;
    verification_policy: string;
    next_allowed_commands: string[];
  }>;
  approvals: Array<{
    approval_id: string;
    action_id: string;
    status: string;
    approved_at_ms: number;
    expires_at_ms: number;
  }>;
  execution_status: { action_count: number; terminal_action_count: number };
  verification_summary: { verified_count: number; mismatch_count: number };
  recovery_summary: { unknown_result_action_count: number };
  next_allowed_commands: string[];
  snapshot_version: number;
};

class FakeEventSource {
  static instances: FakeEventSource[] = [];

  url: string;
  withCredentials: boolean;
  listeners = new Map<string, Array<(event: MessageEvent<string>) => void>>();

  constructor(url: string, init?: EventSourceInit) {
    this.url = url;
    this.withCredentials = Boolean(init?.withCredentials);
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void {
    const current = this.listeners.get(type) ?? [];
    current.push(listener);
    this.listeners.set(type, current);
  }

  close(): void {
    return;
  }

  emit(type: string, payload: Record<string, unknown>, eventId = `${type}-1`): void {
    const event = { data: JSON.stringify(payload), lastEventId: eventId } as MessageEvent<string>;
    for (const listener of this.listeners.get(type) ?? []) {
      listener(event);
    }
  }
}

const originalFetch = globalThis.fetch;

beforeEach(() => {
  localStorage.clear();
  FakeEventSource.instances = [];
  Object.defineProperty(window, "EventSource", { value: FakeEventSource, configurable: true });
  Object.defineProperty(window, "open", { value: vi.fn(), configurable: true });
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  window.history.replaceState(null, "", "/");
});

test("captures the bootstrap fragment before asynchronous startup checks", async () => {
  window.history.replaceState(null, "", "/#bootstrap_secret=secret-1&service_instance_id=svc-1");
  let bootstrapRequested = false;
  installFetch((path) => {
    if (path === "/health/live") {
      window.history.replaceState(null, "", "/");
      return jsonResponse({ status: "LIVE", service_instance_id: "svc-1", release_version: "test", api_contract_version: "1", occurred_at_ms: 1 });
    }
    if (path === "/health/ready") {
      return jsonResponse({ status: "READY", checks: [{ name: "sqlite", state: "READY" }], release_version: "test", api_contract_version: "1", occurred_at_ms: 2 });
    }
    if (path === "/api/v1/session/bootstrap") {
      bootstrapRequested = true;
      return jsonResponse({ session_established: true, service_instance_id: "svc-1", api_contract_version: "1" });
    }
    if (path === "/api/v1/runtime") {
      return jsonResponse({ summary: runtimeSummary([]), api_contract_version: "1" });
    }
    if (path === "/api/v1/google/connection") {
      return jsonResponse(googleConnection());
    }
    if (path === "/api/v1/identity/google-account") {
      return jsonResponse({ account: currentAccount(), api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/conversations?")) {
      return jsonResponse({ items: [], next_cursor: null, api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      return jsonResponse({ source: "gmail", items: [], next_page_token: null, api_contract_version: "1" });
    }
    throw new Error(`Unhandled path ${path}`);
  });

  render(<App />);

  await screen.findByText(/Google/);
  expect(window.location.hash).toBe("");
  expect(bootstrapRequested).toBe(true);
  expect(document.body.textContent).not.toContain("secret-1");
});

test("keeps the fragment until one StrictMode bootstrap request succeeds", async () => {
  window.history.replaceState(null, "", "/#bootstrap_secret=secret-1&service_instance_id=svc-1");
  const paths: string[] = [];
  let bootstrapStarted = false;
  let resolveBootstrap: (response: Response) => void = () => {
    throw new Error("Bootstrap request did not start");
  };
  globalThis.fetch = vi.fn((input: string | URL) => {
    const path = String(input);
    paths.push(path);
    if (path === "/health/live") {
      return Promise.resolve(jsonFetchResponse(liveResponse()));
    }
    if (path === "/health/ready") {
      return Promise.resolve(jsonFetchResponse(readyResponse()));
    }
    if (path === "/api/v1/session/bootstrap") {
      bootstrapStarted = true;
      return new Promise<Response>((resolve) => {
        resolveBootstrap = resolve;
      });
    }
    if (path === "/api/v1/runtime") {
      return Promise.resolve(jsonFetchResponse({ summary: runtimeSummary([]), api_contract_version: "1" }));
    }
    if (path === "/api/v1/google/connection") {
      return Promise.resolve(jsonFetchResponse(googleConnection()));
    }
    if (path === "/api/v1/identity/google-account") {
      return Promise.resolve(jsonFetchResponse({ account: currentAccount(), api_contract_version: "1" }));
    }
    if (path.startsWith("/api/v1/conversations?")) {
      return Promise.resolve(jsonFetchResponse({ items: [], next_cursor: null, api_contract_version: "1" }));
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      return Promise.resolve(jsonFetchResponse({ source: "gmail", items: [], next_page_token: null, api_contract_version: "1" }));
    }
    return Promise.reject(new Error(`Unhandled path ${path}`));
  }) as typeof fetch;

  render(
    <StrictMode>
      <App />
    </StrictMode>,
  );

  await waitFor(() => expect(bootstrapStarted).toBe(true));
  expect(paths.filter((path) => path === "/api/v1/session/bootstrap")).toHaveLength(1);
  expect(paths).not.toContain("/api/v1/runtime");
  expect(window.location.hash).toContain("bootstrap_secret");

  resolveBootstrap(jsonFetchResponse({ session_established: true, service_instance_id: "svc-1", api_contract_version: "1" }));

  await screen.findByText(/Google/);
  expect(window.location.hash).toBe("");
  expect(paths.indexOf("/api/v1/session/bootstrap")).toBeLessThan(paths.indexOf("/api/v1/runtime"));
  expect(paths.indexOf("/api/v1/session/bootstrap")).toBeLessThan(paths.indexOf("/api/v1/google/connection"));
  expect(paths.indexOf("/api/v1/session/bootstrap")).toBeLessThan(paths.indexOf("/api/v1/identity/google-account"));
});

test("starts a run in RESOURCE_SELECTED mode", async () => {
  let conversationCreated = false;
  installFetch((path, init) => {
    if (path === "/health/live") {
      return jsonResponse({ status: "LIVE", service_instance_id: "svc-1", release_version: "test", api_contract_version: "1", occurred_at_ms: 1 });
    }
    if (path === "/health/ready") {
      return jsonResponse({ status: "READY", checks: [{ name: "sqlite", state: "READY" }], release_version: "test", api_contract_version: "1", occurred_at_ms: 2 });
    }
    if (path === "/api/v1/runtime") {
      return jsonResponse({ summary: runtimeSummary([]), api_contract_version: "1" });
    }
    if (path === "/api/v1/google/connection") {
      return jsonResponse(googleConnection());
    }
    if (path === "/api/v1/identity/google-account") {
      return jsonResponse({ account: currentAccount(), api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/conversations?")) {
      return jsonResponse({
        items: conversationCreated
          ? [{ id: "conversation-1", account_id: "account-1", title: "Project sync", created_at_ms: 1, updated_at_ms: 2 }]
          : [],
        next_cursor: null,
        api_contract_version: "1",
      });
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      return jsonResponse({
        source: "gmail",
        items: [
          {
            source: "gmail",
            resource_type: "gmail_thread",
            resource_id: "thread-project",
            parent_id: null,
            title: "Project sync follow-up",
            subtitle: "Need a draft for the Thursday recap.",
            link_url: "https://mail.google.com/mail/u/0/#inbox/thread-project",
            version: "3",
            related_resource_ids: [],
            metadata: {},
          },
        ],
        next_page_token: null,
        api_contract_version: "1",
      });
    }
    if (path === "/api/v1/conversations" && init?.method === "POST") {
      conversationCreated = true;
      return jsonResponse({ conversation_id: "conversation-1" });
    }
    if (path === "/api/v1/runs" && init?.method === "POST") {
      return jsonResponse({
        applied: true,
        result_code: "ACCEPTED",
        run_id: "run-1",
        conversation_id: "conversation-1",
        run_status: "CREATED",
        run_version: 0,
        user_message_id: "message-1",
        workflow_key: "workflow-run-1",
        enqueued: true,
        request_replayed: false,
      });
    }
    if (path === "/api/v1/runs/run-1") {
      return jsonResponse(snapshotPayload({ status: "CREATED", entry_mode: "RESOURCE_SELECTED" }));
    }
    if (path === "/api/v1/runs/run-1/context") {
      return jsonResponse({
        context: {
          run_id: "run-1",
          conversation_id: "conversation-1",
          workflow_key: "workflow-run-1",
          entry_mode: "RESOURCE_SELECTED",
          requested_mode: "AUTO",
          status: "CREATED",
          version: 0,
          request_text: "Summarize the selected thread",
          selected_resource_ids: ["thread-project"],
        },
        api_contract_version: "1",
      });
    }
    throw new Error(`Unhandled path ${path}`);
  });

  const user = userEvent.setup();
  render(<App />);

  const selectControl = await screen.findByRole("checkbox", { name: /선택/ });
  await user.click(selectControl);
  await user.type(screen.getByRole("textbox", { name: "선택한 자료에 대해 질문하거나 업무를 요청하세요" }), "선택 자료를 정리해 줘");
  await user.click(screen.getByRole("button", { name: "보내기" }));

  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/runs",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  const startRunCall = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.find(
    ([path, init]) => path === "/api/v1/runs" && init?.method === "POST",
  );
  const body = JSON.parse(String(startRunCall?.[1].body)) as {
    entry_mode: string;
    selected_resource_ids: string[];
  };
  expect(body.entry_mode).toBe("RESOURCE_SELECTED");
  expect(body.selected_resource_ids).toEqual(["thread-project"]);
});

test("shows approve button for write actions and posts approve command", async () => {
  let approved = false;
  installFetch((path, init) => {
    if (path === "/health/live") {
      return jsonResponse({ status: "LIVE", service_instance_id: "svc-1", release_version: "test", api_contract_version: "1", occurred_at_ms: 1 });
    }
    if (path === "/health/ready") {
      return jsonResponse({ status: "READY", checks: [{ name: "sqlite", state: "READY" }], release_version: "test", api_contract_version: "1", occurred_at_ms: 2 });
    }
    if (path === "/api/v1/runtime") {
      return jsonResponse({ summary: runtimeSummary(["run-1"]), api_contract_version: "1" });
    }
    if (path === "/api/v1/google/connection") {
      return jsonResponse(googleConnection());
    }
    if (path === "/api/v1/identity/google-account") {
      return jsonResponse({ account: currentAccount(), api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/conversations?")) {
      return jsonResponse({
        items: [{ id: "conversation-1", account_id: "account-1", title: "Inbox", created_at_ms: 1, updated_at_ms: 2 }],
        next_cursor: null,
        api_contract_version: "1",
      });
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      return jsonResponse({ source: "gmail", items: [], next_page_token: null, api_contract_version: "1" });
    }
    if (path === "/api/v1/runs/run-1") {
      return jsonResponse(
        snapshotPayload({
          status: approved ? "EXECUTING" : "WAITING_APPROVAL",
          actions: [
            {
              action_id: "action-1",
              tool_name: "tasks_create_task",
              status: approved ? "APPROVED" : "PROPOSED",
              version: approved ? 3 : 2,
              effect_type: "CREATE",
              approval_required: true,
              verification_policy: "GET_COMPARE",
              next_allowed_commands: approved ? [] : ["APPROVE", "MODIFY", "REJECT"],
            },
          ],
        }),
      );
    }
    if (path === "/api/v1/runs/run-1/context") {
      return jsonResponse({
        context: {
          run_id: "run-1",
          conversation_id: "conversation-1",
          workflow_key: "workflow-run-1",
          entry_mode: "AGENT_SEARCH",
          requested_mode: "AUTO",
          status: approved ? "EXECUTING" : "WAITING_APPROVAL",
          version: approved ? 2 : 1,
          request_text: "Prepare the weekly follow-up",
          selected_resource_ids: [],
        },
        api_contract_version: "1",
      });
    }
    if (path === "/api/v1/actions/action-1/approve" && init?.method === "POST") {
      approved = true;
      return jsonResponse({
        applied: true,
        result_code: "ACCEPTED",
        action_id: "action-1",
        action_status: "APPROVED",
        action_version: 3,
        next_allowed_commands: [],
      });
    }
    throw new Error(`Unhandled path ${path}`);
  });

  const user = userEvent.setup();
  render(<App />);

  const approveButton = await screen.findByRole("button", { name: "승인" });
  await user.click(approveButton);

  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/actions/action-1/approve",
      expect.objectContaining({ method: "POST" }),
    ),
  );
});

test("TST-UI-212 reloads a snapshot after SSE recovery without replaying a write", async () => {
  installFetch((path) => {
    if (path === "/health/live") {
      return jsonResponse({ status: "LIVE", service_instance_id: "svc-1", release_version: "test", api_contract_version: "1", occurred_at_ms: 1 });
    }
    if (path === "/health/ready") {
      return jsonResponse({ status: "READY", checks: [{ name: "sqlite", state: "READY" }], release_version: "test", api_contract_version: "1", occurred_at_ms: 2 });
    }
    if (path === "/api/v1/runtime") {
      return jsonResponse({ summary: runtimeSummary(["run-1"]), api_contract_version: "1" });
    }
    if (path === "/api/v1/google/connection") {
      return jsonResponse(googleConnection());
    }
    if (path === "/api/v1/identity/google-account") {
      return jsonResponse({ account: currentAccount(), api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/conversations?")) {
      return jsonResponse({
        items: [{ id: "conversation-1", account_id: "account-1", title: "Inbox", created_at_ms: 1, updated_at_ms: 2 }],
        next_cursor: null,
        api_contract_version: "1",
      });
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      return jsonResponse({ source: "gmail", items: [], next_page_token: null, api_contract_version: "1" });
    }
    if (path === "/api/v1/runs/run-1") {
      return jsonResponse(snapshotPayload({}));
    }
    if (path === "/api/v1/runs/run-1/context") {
      return jsonResponse({
        context: {
          run_id: "run-1",
          conversation_id: "conversation-1",
          workflow_key: "workflow-run-1",
          entry_mode: "AGENT_SEARCH",
          requested_mode: "AUTO",
          status: "WAITING_APPROVAL",
          version: 1,
          request_text: "Prepare the weekly follow-up",
          selected_resource_ids: [],
        },
        api_contract_version: "1",
      });
    }
    throw new Error(`Unhandled path ${path}`);
  });

  render(<App />);

  await screen.findByText("사용자 요청");
  const instance = FakeEventSource.instances[0];
  instance.emit("snapshot_required", { reason: "cursor expired" }, "evt-1");

  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/v1/runs/run-1", expect.any(Object)),
  );
  expect(globalThis.fetch).not.toHaveBeenCalledWith("/api/v1/runs", expect.any(Object));
  expect(FakeEventSource.instances).toHaveLength(1);
});

test("confirms an interrupt and explicitly resolves a mismatch", async () => {
  let stage: "confirmation" | "mismatch" | "completed" = "confirmation";
  installFetch((path, init) => {
    if (path === "/health/live") {
      return jsonResponse(liveResponse());
    }
    if (path === "/health/ready") {
      return jsonResponse(readyResponse());
    }
    if (path === "/api/v1/runtime") {
      return jsonResponse({ summary: runtimeSummary(["run-1"]), api_contract_version: "1" });
    }
    if (path === "/api/v1/google/connection") {
      return jsonResponse(googleConnection());
    }
    if (path === "/api/v1/identity/google-account") {
      return jsonResponse({ account: currentAccount(), api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/conversations?")) {
      return jsonResponse({
        items: [{ id: "conversation-1", account_id: "account-1", title: "Inbox", created_at_ms: 1, updated_at_ms: 2 }],
        next_cursor: null,
        api_contract_version: "1",
      });
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      return jsonResponse({ source: "gmail", items: [], next_page_token: null, api_contract_version: "1" });
    }
    if (path === "/api/v1/runs/run-1") {
      const mismatch = stage === "mismatch";
      return jsonResponse(
        snapshotPayload({
          status: stage === "confirmation" ? "WAITING_CONFIRMATION" : mismatch ? "RECOVERY_REQUIRED" : "COMPLETED",
          version: stage === "confirmation" ? 1 : 2,
          actions: mismatch
            ? [{
                action_id: "action-1",
                tool_name: "tasks_update_task",
                status: "MISMATCH",
                version: 4,
                effect_type: "UPDATE",
                approval_required: false,
                verification_policy: "GET_COMPARE",
                next_allowed_commands: [],
              }]
            : [],
          verification_summary: { verified_count: 0, mismatch_count: mismatch ? 1 : 0 },
        }),
      );
    }
    if (path === "/api/v1/runs/run-1/context") {
      return jsonResponse({
        context: {
          run_id: "run-1",
          conversation_id: "conversation-1",
          workflow_key: "workflow-run-1",
          entry_mode: "AGENT_SEARCH",
          requested_mode: "AUTO",
          status: stage === "confirmation" ? "WAITING_CONFIRMATION" : stage === "mismatch" ? "RECOVERY_REQUIRED" : "COMPLETED",
          version: stage === "confirmation" ? 1 : 2,
          request_text: "Update the task after confirmation",
          selected_resource_ids: [],
        },
        api_contract_version: "1",
      });
    }
    if (path === "/api/v1/runs/run-1/confirm" && init?.method === "POST") {
      stage = "mismatch";
      return jsonResponse({
        applied: true,
        result_code: "ACCEPTED",
        run_id: "run-1",
        run_status: "EXECUTING",
        run_version: 2,
      });
    }
    if (path === "/api/v1/runs/run-1/resolve-recovery" && init?.method === "POST") {
      stage = "completed";
      return jsonResponse({
        applied: true,
        result_code: "TRANSITION_APPLIED",
        run_id: "run-1",
        run_status: "COMPLETED",
        run_version: 3,
      });
    }
    throw new Error(`Unhandled path ${path}`);
  });

  const user = userEvent.setup();
  render(<App />);

  await screen.findByText("확인 요청 정보를 동기화하고 있습니다.");
  expect(screen.getByLabelText("확인 응답")).toBeDisabled();
  FakeEventSource.instances[0].emit("confirmation_required", {
    user_interrupt: { interrupt_id: "interrupt-1", question: "Which task should be updated?" },
  });
  await screen.findByText("Which task should be updated?");
  expect(screen.getByLabelText("확인 응답")).toBeEnabled();
  await user.type(screen.getByLabelText("확인 응답"), "Use the follow-up task");
  await user.click(screen.getByRole("button", { name: "응답 보내기" }));
  await user.click(await screen.findByRole("button", { name: "현재 결과 수용" }));

  expect(globalThis.fetch).toHaveBeenCalledWith(
    "/api/v1/runs/run-1/confirm",
    expect.objectContaining({ method: "POST", body: expect.stringContaining('"interrupt_id":"interrupt-1"') }),
  );
  expect(globalThis.fetch).toHaveBeenCalledWith(
    "/api/v1/runs/run-1/resolve-recovery",
    expect.objectContaining({ method: "POST", body: expect.stringContaining('"resolution_kind":"ACCEPT_PARTIAL"') }),
  );
});

test("starts Google OAuth from the disconnected status action", async () => {
  installFetch((path, init) => {
    if (path === "/health/live") {
      return jsonResponse(liveResponse());
    }
    if (path === "/health/ready") {
      return jsonResponse(readyResponse());
    }
    if (path === "/api/v1/runtime") {
      return jsonResponse({ summary: runtimeSummary([]), api_contract_version: "1" });
    }
    if (path === "/api/v1/google/connection") {
      return jsonResponse({
        ...googleConnection(),
        connected: false,
        credential_state: "DISCONNECTED",
        account_email: null,
        safe_error_code: "TOKEN_EXCHANGE_INVALID_REQUEST",
        safe_error_description: "Google rejected a required token request field.",
      });
    }
    if (path === "/api/v1/settings") {
      return jsonResponse({ settings: settingsPayload(), api_contract_version: "1" });
    }
    if (path === "/api/v1/llm/connection") {
      return jsonResponse({ llm: llmConnectionPayload(), api_contract_version: "1" });
    }
    if (path === "/api/v1/identity/google-account") {
      return jsonResponse({ account: currentAccount(), api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/conversations?")) {
      return jsonResponse({ items: [], next_cursor: null, api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      return jsonResponse({ source: "gmail", items: [], next_page_token: null, api_contract_version: "1" });
    }
    if (path === "/api/v1/google/oauth/start" && init?.method === "POST") {
      return jsonResponse({
        flow_id: "flow-1",
        authorization_url: "http://127.0.0.1:43123/oauth/authorize?state=flow-1",
        callback_url: "http://localhost/callback",
        expires_at_ms: 1000,
        oauth_environment: "DEVELOPMENT",
        scopes: ["gmail.readonly"],
        api_contract_version: "1",
      });
    }
    throw new Error(`Unhandled path ${path}`);
  });

  const user = userEvent.setup();
  render(<App />);

  await screen.findByText(/Google/);
  await user.click(screen.getByRole("button", { name: "설정" }));
  expect(await screen.findByText("TOKEN_EXCHANGE_INVALID_REQUEST")).toBeInTheDocument();
  expect(
    screen.getByText("Google rejected a required token request field."),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Google 연결" }));

  expect(window.open).toHaveBeenCalledWith(
    "http://127.0.0.1:43123/oauth/authorize?state=flow-1",
    "_blank",
    "noopener,noreferrer",
  );
  expect(await screen.findByText("Google 연결 완료를 기다리고 있습니다.")).toBeInTheDocument();
});

test("does not open an unexpected authorization URL returned by the API", async () => {
  installFetch((path, init) => {
    if (path === "/health/live") {
      return jsonResponse(liveResponse());
    }
    if (path === "/health/ready") {
      return jsonResponse(readyResponse());
    }
    if (path === "/api/v1/runtime") {
      return jsonResponse({ summary: runtimeSummary([]), api_contract_version: "1" });
    }
    if (path === "/api/v1/google/connection") {
      return jsonResponse({ ...googleConnection(), connected: false, credential_state: "DISCONNECTED", account_email: null });
    }
    if (path === "/api/v1/identity/google-account") {
      return jsonResponse({ account: currentAccount(), api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/conversations?")) {
      return jsonResponse({ items: [], next_cursor: null, api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      return jsonResponse({ source: "gmail", items: [], next_page_token: null, api_contract_version: "1" });
    }
    if (path === "/api/v1/google/oauth/start" && init?.method === "POST") {
      return jsonResponse({
        flow_id: "flow-1",
        authorization_url: "https://invalid.example/authorization",
        callback_url: "http://127.0.0.1/callback",
        expires_at_ms: 1000,
        oauth_environment: "DEVELOPMENT",
        scopes: ["gmail.readonly"],
        api_contract_version: "1",
      });
    }
    throw new Error(`Unhandled path ${path}`);
  });

  const user = userEvent.setup();
  render(<App />);

  await user.click(await screen.findByRole("button", { name: "Google 연결" }));
  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/google/oauth/start",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  expect(window.open).not.toHaveBeenCalled();
  expect(screen.getByText("Google 연결을 시작하지 못했습니다.")).toBeInTheDocument();
});

test("disconnects Google and refreshes the runtime summary", async () => {
  let disconnected = false;
  installFetch((path, init) => {
    if (path === "/health/live") {
      return jsonResponse(liveResponse());
    }
    if (path === "/health/ready") {
      return jsonResponse(readyResponse());
    }
    if (path === "/api/v1/runtime") {
      return jsonResponse({
        summary: {
          ...runtimeSummary([]),
          google: disconnected ? "DISCONNECTED" : "CONNECTED",
        },
        api_contract_version: "1",
      });
    }
    if (path === "/api/v1/google/connection") {
      return jsonResponse(
        disconnected
          ? {
              ...googleConnection(),
              connected: false,
              credential_state: "DISCONNECTED",
              account_email: null,
            }
          : googleConnection(),
      );
    }
    if (path === "/api/v1/settings") {
      return jsonResponse({ settings: settingsPayload(), api_contract_version: "1" });
    }
    if (path === "/api/v1/llm/connection") {
      return jsonResponse({ llm: llmConnectionPayload(), api_contract_version: "1" });
    }
    if (path === "/api/v1/identity/google-account") {
      return jsonResponse({ account: currentAccount(), api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/conversations?")) {
      return jsonResponse({ items: [], next_cursor: null, api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      return jsonResponse({
        source: "gmail",
        items: [gmailThread()],
        next_page_token: null,
        api_contract_version: "1",
      });
    }
    if (path === "/api/v1/google/disconnect" && init?.method === "POST") {
      disconnected = true;
      return jsonResponse({
        ...googleConnection(),
        connected: false,
        credential_state: "DISCONNECTED",
        account_email: null,
      });
    }
    throw new Error(`Unhandled path ${path}`);
  });

  const user = userEvent.setup();
  render(<App />);

  await screen.findByRole("checkbox", { name: /선택/ });
  await user.click(screen.getByRole("button", { name: "설정" }));
  await user.click(screen.getByRole("button", { name: "연결 해제" }));

  await screen.findByText("Google 미연결");
  expect(screen.queryByRole("checkbox", { name: /선택/ })).not.toBeInTheDocument();
});

test("submits cancel, resume, and retry actions while showing unknown-result recovery", async () => {
  let cancelled = false;
  let resumed = false;
  let retried = false;
  installFetch((path, init) => {
    if (path === "/health/live") {
      return jsonResponse(liveResponse());
    }
    if (path === "/health/ready") {
      return jsonResponse(readyResponse());
    }
    if (path === "/api/v1/runtime") {
      return jsonResponse({ summary: runtimeSummary(["run-1"]), api_contract_version: "1" });
    }
    if (path === "/api/v1/google/connection") {
      return jsonResponse(googleConnection());
    }
    if (path === "/api/v1/identity/google-account") {
      return jsonResponse({ account: currentAccount(), api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/conversations?")) {
      return jsonResponse({
        items: [{ id: "conversation-1", account_id: "account-1", title: "Inbox", created_at_ms: 1, updated_at_ms: 2 }],
        next_cursor: null,
        api_contract_version: "1",
      });
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      return jsonResponse({ source: "gmail", items: [gmailThread()], next_page_token: null, api_contract_version: "1" });
    }
    if (path === "/api/v1/runs/run-1") {
      return jsonResponse(
        snapshotPayload({
          status: resumed ? "EXECUTING" : cancelled ? "CANCEL_REQUESTED" : "RECOVERY_REQUIRED",
          actions: [
            {
              action_id: "action-failed",
              tool_name: "tasks_create_task",
              status: retried ? "PENDING" : "FAILED",
              version: retried ? 3 : 2,
              effect_type: "CREATE",
              approval_required: false,
              verification_policy: "GET_COMPARE",
              next_allowed_commands: retried ? [] : ["PREPARE_RETRY"],
            },
            {
              action_id: "action-unknown",
              tool_name: "calendar_update_event",
              status: "UNKNOWN_RESULT",
              version: 4,
              effect_type: "UPDATE",
              approval_required: false,
              verification_policy: "GET_COMPARE",
              next_allowed_commands: [],
            },
          ],
          recovery_summary: { unknown_result_action_count: 1 },
        }),
      );
    }
    if (path === "/api/v1/runs/run-1/context") {
      return jsonResponse({
        context: {
          run_id: "run-1",
          conversation_id: "conversation-1",
          workflow_key: "workflow-run-1",
          entry_mode: "AGENT_SEARCH",
          requested_mode: "AUTO",
          status: resumed ? "EXECUTING" : cancelled ? "CANCEL_REQUESTED" : "RECOVERY_REQUIRED",
          version: 1,
          request_text: "Recover the failed write",
          selected_resource_ids: [],
        },
        api_contract_version: "1",
      });
    }
    if (path === "/api/v1/runs/run-1/cancel" && init?.method === "POST") {
      cancelled = true;
      return jsonResponse({
        applied: true,
        result_code: "ACCEPTED",
        run_id: "run-1",
        run_status: "CANCEL_REQUESTED",
        run_version: 2,
      });
    }
    if (path === "/api/v1/runs/run-1/resume" && init?.method === "POST") {
      resumed = true;
      return jsonResponse({
        applied: true,
        result_code: "ACCEPTED",
        run_id: "run-1",
        run_status: "EXECUTING",
        run_version: 3,
      });
    }
    if (path === "/api/v1/actions/action-failed/prepare-retry" && init?.method === "POST") {
      retried = true;
      return jsonResponse({
        applied: true,
        result_code: "ACCEPTED",
        action_id: "action-failed",
        action_status: "PENDING",
        action_version: 3,
        next_allowed_commands: [],
      });
    }
    throw new Error(`Unhandled path ${path}`);
  });

  const user = userEvent.setup();
  render(<App />);

  await screen.findByText("결과 불명 작업 1건을 확인하고 있습니다.");
  await user.click(screen.getByRole("button", { name: "취소" }));
  await user.click(screen.getByRole("button", { name: "재개" }));
  await user.click(screen.getByRole("button", { name: "다시 준비" }));

  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/actions/action-failed/prepare-retry",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  expect(screen.getByText("실제 결과를 확인하는 중입니다. 새 쓰기 실행은 잠시 막혀 있습니다.")).toBeInTheDocument();
});

test("opens only safe Google links from resource items", async () => {
  installFetch((path) => {
    if (path === "/health/live") {
      return jsonResponse(liveResponse());
    }
    if (path === "/health/ready") {
      return jsonResponse(readyResponse());
    }
    if (path === "/api/v1/runtime") {
      return jsonResponse({ summary: runtimeSummary([]), api_contract_version: "1" });
    }
    if (path === "/api/v1/google/connection") {
      return jsonResponse(googleConnection());
    }
    if (path === "/api/v1/identity/google-account") {
      return jsonResponse({ account: currentAccount(), api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/conversations?")) {
      return jsonResponse({ items: [], next_cursor: null, api_contract_version: "1" });
    }
    if (path === "/api/v1/resources/gmail/thread-project") {
      return jsonResponse(gmailDetail("thread-project", { canonical_url: "javascript:alert('xss')" }));
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      return jsonResponse({
        source: "gmail",
        items: [{ ...gmailThread(), link_url: "javascript:alert('xss')" }],
        next_page_token: null,
        api_contract_version: "1",
      });
    }
    throw new Error(`Unhandled path ${path}`);
  });

  const user = userEvent.setup();
  render(<App />);

  await user.click(await screen.findByRole("button", { name: /Project sync follow-up/ }));
  expect(screen.queryByRole("button", { name: "원본 열기" })).not.toBeInTheDocument();
});

test("saves llm settings and stores, tests, then deletes the api key", async () => {
  let requestedRuntimeMode = "API_LLM";
  let externalLLMConsent = false;
  let credentialState = "MISSING";
  installFetch((path, init) => {
    if (path === "/health/live") {
      return jsonResponse(liveResponse());
    }
    if (path === "/health/ready") {
      return jsonResponse(readyResponse());
    }
    if (path === "/api/v1/runtime") {
      return jsonResponse({
        summary: runtimeSummary([], {
          llm: llmConnectionPayload({
            requested_mode: requestedRuntimeMode,
            external_llm_consent: externalLLMConsent,
            api_provider: {
              credential_state: credentialState,
              availability: credentialState === "MISSING" ? "NOT_CONFIGURED" : "AVAILABLE",
              last_probe: 1,
              safe_error_code: null,
            },
          }),
        }),
        api_contract_version: "1",
      });
    }
    if (path === "/api/v1/google/connection") {
      return jsonResponse(googleConnection());
    }
    if (path === "/api/v1/settings" && (!init || init.method === "GET")) {
      return jsonResponse({
        settings: settingsPayload({
          requested_runtime_mode: requestedRuntimeMode,
          external_llm_consent: externalLLMConsent,
        }),
        api_contract_version: "1",
      });
    }
    if (path === "/api/v1/llm/connection" && (!init || init.method === "GET")) {
      return jsonResponse({
        llm: llmConnectionPayload({
          requested_mode: requestedRuntimeMode,
          external_llm_consent: externalLLMConsent,
          api_provider: {
            credential_state: credentialState,
            availability: credentialState === "MISSING" ? "NOT_CONFIGURED" : "AVAILABLE",
            last_probe: 1,
            safe_error_code: null,
          },
        }),
        api_contract_version: "1",
      });
    }
    if (path === "/api/v1/identity/google-account") {
      return jsonResponse({ account: currentAccount(), api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/conversations?")) {
      return jsonResponse({ items: [], next_cursor: null, api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      return jsonResponse({ source: "gmail", items: [], next_page_token: null, api_contract_version: "1" });
    }
    if (path === "/api/v1/settings" && init?.method === "PATCH") {
      const body = JSON.parse(String(init.body)) as {
        requested_runtime_mode: string;
        external_llm_consent: boolean;
      };
      requestedRuntimeMode = body.requested_runtime_mode;
      externalLLMConsent = body.external_llm_consent;
      return jsonResponse({
        settings: settingsPayload({
          requested_runtime_mode: requestedRuntimeMode,
          external_llm_consent: externalLLMConsent,
        }),
        api_contract_version: "1",
      });
    }
    if (path === "/api/v1/llm/api-key" && init?.method === "POST") {
      credentialState = "AVAILABLE";
      return jsonResponse({ credential_state: credentialState, api_contract_version: "1" });
    }
    if (path === "/api/v1/llm/test" && init?.method === "POST") {
      return jsonResponse({
        llm: llmConnectionPayload({
          requested_mode: requestedRuntimeMode,
          external_llm_consent: externalLLMConsent,
          api_provider: {
            credential_state: credentialState,
            availability: "AVAILABLE",
            last_probe: 2,
            safe_error_code: null,
          },
        }),
        api_contract_version: "1",
      });
    }
    if (path === "/api/v1/llm/api-key" && init?.method === "DELETE") {
      credentialState = "MISSING";
      return jsonResponse({ credential_state: credentialState, api_contract_version: "1" });
    }
    throw new Error(`Unhandled path ${path}`);
  });

  const user = userEvent.setup();
  render(<App />);

  await screen.findByText(/Google/);
  await user.click(screen.getByRole("button", { name: "설정" }));
  await screen.findByText("Requested mode");
  await user.selectOptions(screen.getByDisplayValue("API_LLM"), "AUTO");
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "LLM 설정 저장" }));
  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/settings",
      expect.objectContaining({ method: "PATCH" }),
    ),
  );

  await user.selectOptions(screen.getByDisplayValue("KEYRING"), "SESSION_MEMORY");
  await user.type(screen.getByPlaceholderText("sk-..."), "sk-phase-m");
  await user.click(screen.getByRole("button", { name: "API 키 저장" }));
  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/llm/api-key",
      expect.objectContaining({ method: "POST" }),
    ),
  );

  await user.click(screen.getByRole("button", { name: "연결 테스트" }));
  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/llm/test",
      expect.objectContaining({ method: "POST" }),
    ),
  );

  await user.click(screen.getByRole("button", { name: "API 키 삭제" }));
  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/llm/api-key",
      expect.objectContaining({ method: "DELETE" }),
    ),
  );
});

test("TST-UI-201 header shows product, connection, account, help, settings, and safe status", async () => {
  installUiContractFetch();
  render(<App />);

  await screen.findByText("승인이 필요합니다.");
  expect(screen.getByText("user@example.com")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "도움말" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "설정" })).toBeInTheDocument();
  expect(screen.getByText("승인이 필요합니다.")).toBeInTheDocument();
  expect(screen.queryByText("WAITING_APPROVAL")).not.toBeInTheDocument();
});

test("TST-UI-202 renders the left, center, and right workspace panels", async () => {
  installUiContractFetch();
  render(<App />);

  await screen.findByRole("list", { name: "Google 업무 자료" });
  expect(screen.getByRole("region", { name: "선택 자료 상세" })).toBeInTheDocument();
  expect(screen.getByText("대화")).toBeInTheDocument();
  expect(screen.getByText("최근 실행")).toBeInTheDocument();
});

test("TST-UI-203 resource row supports focus, selection, and keyboard-accessible controls", async () => {
  const user = userEvent.setup();
  installUiContractFetch();
  render(<App />);

  const row = await screen.findByRole("button", { name: /첫 번째 자료/ });
  await user.click(row);
  expect(row).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("checkbox", { name: "첫 번째 자료 선택" })).not.toBeChecked();
  expect(screen.getByText("GMAIL")).toBeInTheDocument();
  expect(screen.getByText("TASKS")).toBeInTheDocument();
  expect(screen.getByText("CALENDAR")).toBeInTheDocument();
});

test("TST-UI-204 uses page size 10, sequential page tokens, and cached numeric pages", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch();
  render(<App />);

  await screen.findByText("첫 번째 자료");
  const firstPage = requests.find((request) => request.path.startsWith("/api/v1/resources/gmail"));
  expect(firstPage?.path).toContain("page_size=10");
  await user.click(screen.getByRole("button", { name: "다음" }));
  await screen.findByText("두 번째 자료");
  expect(requests.at(-1)?.path).toContain("page_token=page-2");
  const countAfterNext = requests.length;
  await user.click(screen.getByRole("button", { name: "1" }));
  await screen.findByText("첫 번째 자료");
  expect(requests).toHaveLength(countAfterNext);
  expect(screen.queryByRole("button", { name: "3" })).not.toBeInTheDocument();
});

test("TST-UI-205 does not render a fake resource count", async () => {
  installUiContractFetch();
  render(<App />);

  await screen.findByText("첫 번째 자료");
  expect(screen.queryByText(/총 .*건/)).not.toBeInTheDocument();
});

test("does not expose a technical resource ID in the row or viewer", async () => {
  const technicalId = "19fe92f3e539543b";
  installUiContractFetch({
    resource: {
      title: technicalId,
      subtitle: technicalId,
      metadata: {
        sender: "김대리",
        sender_email: "kim@example.com",
        subject: "Q2 마케팅 캠페인 결과 공유",
        snippet: "후속 조치 검토를 요청드립니다.",
        received_at: "2025-05-24 09:15",
      },
    },
  });
  const user = userEvent.setup();
  render(<App />);

  const row = await screen.findByRole("button", { name: /Q2 마케팅 캠페인 결과 공유/ });
  expect(screen.getByText("김대리 <kim@example.com>")).toBeInTheDocument();
  expect(screen.getByText(/2025/)).toBeInTheDocument();
  expect(screen.queryByText("2025-05-24 09:15")).not.toBeInTheDocument();
  expect(screen.getByText("후속 조치 검토를 요청드립니다.")).toBeInTheDocument();
  expect(screen.queryByText(technicalId)).not.toBeInTheDocument();
  await user.click(row);
  expect(screen.getByRole("heading", { name: "Q2 마케팅 캠페인 결과 공유" })).toBeInTheDocument();
  expect(screen.queryByText(technicalId)).not.toBeInTheDocument();
});

test("uses the Gmail subject instead of a generic resource fallback title", async () => {
  installUiContractFetch({
    resource: {
      title: "메일 자료",
      metadata: { subject: "예산 검토 요청", snippet: "검토 의견을 부탁드립니다." },
    },
  });
  render(<App />);

  await screen.findByText("예산 검토 요청");
  expect(screen.queryByText("메일 자료")).not.toBeInTheDocument();
});

test("TST-UI-206 keeps focus separate from multiple selected resources and sends selected IDs", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch({ twoItems: true });
  render(<App />);

  await screen.findByText("첫 번째 자료");
  const selectControls = screen.getAllByRole("checkbox", { name: /선택/ });
  await user.click(selectControls[0]!);
  await user.click(selectControls[1]!);
  await user.click(screen.getByRole("button", { name: /두 번째 자료/ }));
  expect(screen.getByRole("heading", { name: "두 번째 자료" })).toBeInTheDocument();
  expect(screen.getByText("요청에 사용할 자료 2개")).toBeInTheDocument();
  expect(screen.getByText("첫 번째 자료 · 두 번째 자료")).toBeInTheDocument();
  await user.type(screen.getByRole("textbox", { name: "선택한 자료에 대해 질문하거나 업무를 요청하세요" }), "선택 자료 정리");
  await user.click(screen.getByRole("button", { name: "보내기" }));
  const start = requests.find((request) => request.path === "/api/v1/runs");
  const body = JSON.parse(String(start?.init?.body)) as { entry_mode: string; selected_resource_ids: string[] };
  expect(body).toMatchObject({
    entry_mode: "RESOURCE_SELECTED",
    selected_resource_ids: ["resource-1", "resource-2"],
  });
  expect(new Set(body.selected_resource_ids).size).toBe(2);
});

test("TST-UI-207 uses AGENT_SEARCH without selection and quick action does not write directly", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch();
  render(<App />);

  await screen.findByText("첫 번째 자료");
  expect(screen.queryByText(/요청에 사용할 자료/)).not.toBeInTheDocument();
  await user.type(screen.getByRole("textbox", { name: "무엇을 도와드릴까요?" }), "메일을 찾아줘");
  await user.click(screen.getByRole("button", { name: "보내기" }));
  const start = requests.find((request) => request.path === "/api/v1/runs");
  expect(JSON.parse(String(start?.init?.body))).toMatchObject({ entry_mode: "AGENT_SEARCH" });
  expect(requests.some((request) => request.path.includes("/actions/") || request.path.includes("gmail/send"))).toBe(false);
});

test("TST-UI-208 Gmail viewer and approval use only available projection fields", async () => {
  installUiContractFetch({ action: true });
  render(<App />);

  await screen.findByText("첫 번째 자료");
  await userEvent.setup().click(screen.getByRole("button", { name: /첫 번째 자료/ }));
  expect(await screen.findByText("실제 메일 본문입니다.")).toBeInTheDocument();
  expect(screen.getByText("김대리 <kim@example.com>")).toBeInTheDocument();
  expect(screen.getByText(/받는 사람 user@example.com/)).toBeInTheDocument();
  expect(screen.getByText("승인 상세")).toBeInTheDocument();
  expect(screen.queryByText("Evidence")).not.toBeInTheDocument();
});

test("Gmail detail shows loading, retries a safe error, and renders the actual body", async () => {
  const user = userEvent.setup();
  installUiContractFetch({ detailErrorOnce: true });
  render(<App />);

  await user.click(await screen.findByRole("button", { name: /첫 번째 자료/ }));
  expect(await screen.findByRole("alert")).toHaveTextContent("메일 내용을 불러오지 못했습니다.");
  await user.click(screen.getByRole("button", { name: "다시 시도" }));
  expect(await screen.findByText("실제 메일 본문입니다.")).toBeInTheDocument();
});

test("Gmail detail keeps an empty body honest and never exposes IDs or raw dates", async () => {
  const technicalId = "19fe92f3e539543b";
  installUiContractFetch({
    resource: {
      resource_id: technicalId,
      title: "업무 확인",
      metadata: { received_at: "Mon, 10 Aug 2026 09:15:00 +0900" },
    },
    detail: {
      resource_id: technicalId,
      message_id: "19fe92f3e539543c",
      body: null,
      received_at: "Mon, 10 Aug 2026 09:15:00 +0900",
    },
  });
  render(<App />);

  await userEvent.setup().click(await screen.findByRole("button", { name: /업무 확인/ }));
  expect(await screen.findByText("표시할 메일 내용이 없습니다.")).toBeInTheDocument();
  expect(document.body.textContent).not.toContain(technicalId);
  expect(document.body.textContent).not.toContain("Mon, 10 Aug 2026 09:15:00 +0900");
});

test("TST-UI-209 renders independent approval commands with versions and disables duplicate submission", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch({ action: true });
  render(<App />);

  await screen.findByRole("button", { name: "승인" });
  await user.click(screen.getByRole("button", { name: "승인" }));
  const approve = requests.find((request) => request.path.endsWith("/approve"));
  expect(JSON.parse(String(approve?.init?.body))).toMatchObject({ expected_version: 7 });
  expect(screen.getByText("승인 상세")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "수정" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "건너뛰기" })).toBeInTheDocument();
});

test("TST-UI-210 filters conversations and shows recent execution fallback", async () => {
  const user = userEvent.setup();
  installUiContractFetch({ conversations: true, run: false });
  render(<App />);

  await screen.findByText("업무 대화");
  await user.type(screen.getByRole("textbox", { name: "대화 검색" }), "없는 대화");
  expect(screen.queryByText("업무 대화")).not.toBeInTheDocument();
  expect(screen.getByText("표시할 실행 기록이 없습니다.")).toBeInTheDocument();
});

test("TST-UI-211 shows loading, empty, error, focus, and disabled pagination states", async () => {
  installUiContractFetch({ empty: true });
  render(<App />);

  await screen.findByText("표시할 자료가 없습니다.");
  expect(screen.getByRole("button", { name: "이전" })).toBeDisabled();
  expect(screen.getByRole("textbox", { name: "무엇을 도와드릴까요?" })).toBeInTheDocument();
});

test("composer exposes one prompt, has no clear button, and retains the send control", async () => {
  installUiContractFetch();
  render(<App />);

  const composer = await screen.findByRole("textbox", { name: "무엇을 도와드릴까요?" });
  expect(composer).toHaveAttribute("placeholder", "무엇을 도와드릴까요?");
  expect(screen.queryByText("무엇을 도와드릴까요?")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "입력 지우기" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "보내기" })).toHaveAttribute("title", "보내기");
});

test("TST-UI-213 hides raw runtime status and has no native window controls", async () => {
  installUiContractFetch({ status: "SINGLE" });
  render(<App />);

  await screen.findByText("작업을 처리하고 있습니다.");
  expect(screen.queryByText("SINGLE")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /최소화|최대화|닫기/ })).not.toBeInTheDocument();
});

function installUiContractFetch(options: {
  action?: boolean;
  conversations?: boolean;
  detail?: Record<string, unknown>;
  detailErrorOnce?: boolean;
  empty?: boolean;
  run?: boolean;
  resource?: Partial<ReturnType<typeof gmailThread>>;
  status?: string;
  twoItems?: boolean;
} = {}): Array<{ path: string; init?: RequestInit }> {
  const requests: Array<{ path: string; init?: RequestInit }> = [];
  let detailAttempts = 0;
  globalThis.fetch = vi.fn(async (input: string | URL, init?: RequestInit) => {
    const path = String(input);
    requests.push({ path, init });
    if (path === "/health/live") return jsonFetchResponse(liveResponse());
    if (path === "/health/ready") return jsonFetchResponse(readyResponse());
    if (path === "/api/v1/runtime") return jsonFetchResponse({ summary: runtimeSummary(options.run === false ? [] : ["run-1"], { llm: {} }), api_contract_version: "1" });
    if (path === "/api/v1/google/connection") return jsonFetchResponse(googleConnection());
    if (path === "/api/v1/identity/google-account") return jsonFetchResponse({ account: currentAccount(), api_contract_version: "1" });
    if (path.startsWith("/api/v1/conversations?")) {
      return jsonFetchResponse({ items: options.conversations ? [{ id: "conversation-1", account_id: "account-1", title: "업무 대화", updated_at_ms: 1, created_at_ms: 1 }] : [], next_cursor: null, api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/resources/gmail/") && !path.includes("?")) {
      detailAttempts += 1;
      if (options.detailErrorOnce && detailAttempts === 1) {
        return jsonFetchResponse({
          error_code: "UPSTREAM_UNAVAILABLE",
          user_message: "메일 내용을 불러오지 못했습니다.",
          retryable: true,
          request_id: "request-1",
          api_contract_version: "1",
        }, 502);
      }
      const resourceId = decodeURIComponent(path.split("/").at(-1) ?? "resource-1");
      const metadata: Record<string, unknown> = options.resource?.metadata ?? {};
      return jsonFetchResponse({
        ...gmailDetail(resourceId, {
          subject: typeof metadata.subject === "string"
            ? metadata.subject
            : options.resource?.title ?? (resourceId === "resource-2" ? "두 번째 자료" : "첫 번째 자료"),
          sender_name: typeof metadata.sender_name === "string"
            ? metadata.sender_name
            : typeof metadata.sender === "string" ? metadata.sender : "김대리",
          sender_email: typeof metadata.sender_email === "string" ? metadata.sender_email : "kim@example.com",
          received_at: typeof metadata.received_at === "string" ? metadata.received_at : "Mon, 10 Aug 2026 09:15:00 +0900",
        }),
        ...options.detail,
      });
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      const items = options.empty ? [] : path.includes("page_token=page-2")
        ? [{ ...gmailThread(), resource_id: "resource-2", title: "두 번째 자료" }]
        : [
            { ...gmailThread(), ...options.resource, resource_id: "resource-1", title: options.resource?.title ?? "첫 번째 자료" },
            ...(options.twoItems ? [{ ...gmailThread(), resource_id: "resource-2", title: "두 번째 자료" }] : []),
          ];
      return jsonFetchResponse({ source: "gmail", items, next_page_token: options.empty || options.twoItems || path.includes("page_token=page-2") ? null : "page-2", api_contract_version: "1" });
    }
    if (path === "/api/v1/conversations" && init?.method === "POST") return jsonFetchResponse({ conversation_id: "conversation-1" });
    if (path === "/api/v1/runs" && init?.method === "POST") return jsonFetchResponse({ applied: true, result_code: "ACCEPTED", run_id: "run-1", conversation_id: "conversation-1", run_status: "WAITING_APPROVAL", run_version: 1, user_message_id: "message-1", workflow_key: "workflow-1", enqueued: true, request_replayed: false });
    if (path === "/api/v1/runs/run-1") return jsonFetchResponse(snapshotPayload({ status: options.status ?? "WAITING_APPROVAL", actions: options.action ? [{ action_id: "action-1", tool_name: "gmail_draft", status: "PROPOSED", version: 7, effect_type: "CREATE", approval_required: true, verification_policy: "GET_COMPARE", next_allowed_commands: [] }] : [] }));
    if (path === "/api/v1/runs/run-1/context") return jsonFetchResponse({ context: null, api_contract_version: "1" });
    if (path.includes("/api/v1/actions/") && init?.method === "POST") return jsonFetchResponse({ applied: true, result_code: "OK", action_id: "action-1", action_status: "APPROVED", action_version: 8, next_allowed_commands: [] });
    throw new Error(`Unhandled path ${path}`);
  }) as typeof fetch;
  return requests;
}

function installFetch(handler: (path: string, init?: RequestInit) => MockResponse): void {
  globalThis.fetch = vi.fn(async (input: string | URL, init?: RequestInit) => {
    const response = handler(String(input), init);
    return new Response(JSON.stringify(response.json ?? {}), {
      status: response.status ?? 200,
      headers: {
        "Content-Type": "application/json",
        ...(response.headers ?? {}),
      },
    });
  }) as typeof fetch;
}

function jsonResponse(json: unknown, status = 200): MockResponse {
  return { status, json };
}

function jsonFetchResponse(json: unknown, status = 200): Response {
  return new Response(JSON.stringify(json), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function liveResponse() {
  return {
    status: "LIVE",
    service_instance_id: "svc-1",
    release_version: "test",
    api_contract_version: "1",
    occurred_at_ms: 1,
  };
}

function readyResponse() {
  return {
    status: "READY",
    checks: [{ name: "sqlite", state: "READY" }],
    release_version: "test",
    api_contract_version: "1",
    occurred_at_ms: 2,
  };
}

function runtimeSummary(openRunIds: string[], overrides: Record<string, unknown> = {}) {
  return {
    google: "CONNECTED",
    mcp: "READY",
    api_llm: "NOT_CONFIGURED",
    ollama: "NOT_AVAILABLE",
    deployment_profile: "test",
    recovery_required_run_ids: [],
    open_run_ids: openRunIds,
    ...overrides,
  };
}

function settingsPayload(overrides: Record<string, unknown> = {}) {
  return {
    config_schema_version: 1,
    deployment_profile: "LOCAL_CAPABLE",
    requested_runtime_mode: "API_LLM",
    default_calendar_id: null,
    default_tasklist_id: null,
    timezone: "Asia/Seoul",
    work_hours: { days: [0, 1, 2, 3, 4], start: "09:00", end: "18:00" },
    approval_ttl_minutes: 30,
    run_retention_days: 30,
    external_llm_consent: false,
    ollama_endpoint: "http://127.0.0.1:11434",
    approved_model_id: "approved-model",
    log_level: "INFO",
    ...overrides,
  };
}

function llmConnectionPayload(overrides: Record<string, unknown> = {}) {
  return {
    build_profile: "LOCAL_CAPABLE",
    requested_mode: "API_LLM",
    available_modes: ["API_LLM", "LOCAL_GPU", "AUTO"],
    actual_runtime: null,
    external_llm_consent: false,
    api_provider: {
      credential_state: "MISSING",
      availability: "NOT_CONFIGURED",
      last_probe: 1,
      safe_error_code: null,
    },
    ollama: {
      visible: true,
      availability: "AVAILABLE",
      version: "0.3.0",
      endpoint_state: "CONFIGURED",
      approved_model_state: "APPROVED",
      hardware_capability: {
        cpu_arch: "x86_64",
        core_summary: "8",
        memory_bytes: 17179869184,
        gpu_present: true,
        gpu_vendor: "NVIDIA",
        gpu_name: "Test GPU",
        gpu_memory_bytes: 8589934592,
        capability_status: "VALIDATED",
        safe_reason_codes: [],
      },
      last_probe: 1,
      safe_error_code: null,
    },
    ...overrides,
  };
}

function googleConnection() {
  return {
    connected: true,
    credential_state: "CONNECTED",
    account_email: "user@example.com",
    display_name: "User",
    granted_scopes: ["gmail.readonly"],
    missing_scopes: [],
    reauth_required: false,
    oauth_environment: "DEVELOPMENT",
    last_checked_at_ms: 3,
    api_contract_version: "1",
  };
}

function currentAccount() {
  return {
    account_id: "account-1",
    email: "user@example.com",
    display_name: "User",
  };
}

function gmailThread() {
  return {
    source: "gmail",
    resource_type: "gmail_thread",
    resource_id: "thread-project",
    parent_id: null,
    title: "Project sync follow-up",
    subtitle: "Need a draft for the Thursday recap.",
    link_url: "https://mail.google.com/mail/u/0/#inbox/thread-project",
    version: "3",
    related_resource_ids: [],
    metadata: {},
  };
}

function gmailDetail(resourceId = "thread-project", overrides: Record<string, unknown> = {}) {
  return {
    resource_id: resourceId,
    message_id: "message-project-2",
    sender_name: "김대리",
    sender_email: "kim@example.com",
    recipients: ["user@example.com"],
    cc: [],
    subject: "Project sync follow-up",
    received_at: "Mon, 10 Aug 2026 09:15:00 +0900",
    body: "실제 메일 본문입니다.",
    attachments: [],
    canonical_url: `https://mail.google.com/mail/u/0/#inbox/${resourceId}`,
    api_contract_version: "1",
    ...overrides,
  };
}

function snapshotPayload(overrides: Partial<SnapshotShape>) {
  return {
    snapshot: {
      ...defaultSnapshot(),
      ...overrides,
    },
    api_contract_version: "1",
  };
}

function defaultSnapshot(): SnapshotShape {
  return {
    run_id: "run-1",
    conversation_id: "conversation-1",
    status: "WAITING_APPROVAL",
    version: 1,
    entry_mode: "AGENT_SEARCH",
    requested_mode: "AUTO",
    actual_runtime: "API_LLM",
    started_at_ms: 1,
    finished_at_ms: null,
    active_plan: {
      plan_id: "plan-1",
      revision_no: 1,
      status: "WAITING_APPROVAL",
      summary_text: "Create follow-up tasks",
      created_at_ms: 1,
    },
    actions: [],
    approvals: [],
    execution_status: { action_count: 1, terminal_action_count: 0 },
    verification_summary: { verified_count: 0, mismatch_count: 0 },
    recovery_summary: { unknown_result_action_count: 0 },
    next_allowed_commands: ["RESUME", "CANCEL"],
    snapshot_version: 1,
  };
}
