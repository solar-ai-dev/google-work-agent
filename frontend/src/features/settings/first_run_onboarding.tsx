import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiClientError } from "../../api/client";
import type { CalendarContainer, TaskListContainer } from "../../api/contract";
import type { RuntimeSummary } from "../diagnostics";
import { listCalendars, listTaskLists } from "../resource_browser/api/list_resources";
import type { GoogleConnection } from "./api/google_connection_operations";
import { getSettings, type SettingsView } from "./api/get_settings";
import { getLlmCredentialStatus, storeLlmCredential, type LlmCredentialStatus } from "./api/llm_credential_operations";
import { updateSettings } from "./api/update_settings";

type Props = {
  runtime: RuntimeSummary;
  google: GoogleConnection;
  onConnectGoogle: () => void;
  onRefreshConnections: () => Promise<void>;
  onComplete: (timezone: string) => void;
};

export function FirstRunOnboardingScreen({
  runtime,
  google,
  onConnectGoogle,
  onRefreshConnections,
  onComplete,
}: Props): JSX.Element {
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [settings, setSettings] = useState<SettingsView | null>(null);
  const [llm, setLLM] = useState<LlmCredentialStatus | null>(null);
  const [consent, setConsent] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [storageMode, setStorageMode] = useState<"KEYRING" | "SESSION_ONLY">("KEYRING");
  const [calendarId, setCalendarId] = useState("");
  const [taskListId, setTaskListId] = useState("");
  const [calendars, setCalendars] = useState<CalendarContainer[]>([]);
  const [taskLists, setTaskLists] = useState<TaskListContainer[]>([]);
  const [timezone, setTimezone] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Seoul");
  const commandIds = useRef(new Map<string, string>());

  useEffect(() => {
    let active = true;
    void Promise.all([getSettings(), getLlmCredentialStatus()])
      .then(([settingsResponse, llmResponse]) => {
        if (!active) return;
        setSettings(settingsResponse);
        setLLM(llmResponse);
        setConsent(settingsResponse.external_llm_consent);
        setCalendarId(settingsResponse.default_calendar_id ?? "");
        setTaskListId(settingsResponse.default_tasklist_id ?? "");
        setTimezone(settingsResponse.timezone);
      })
      .catch((cause: unknown) => {
        if (active) setError(errorMessage(cause, "설정 상태를 불러오지 못했습니다."));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (google.connection_status !== "CONNECTED") return;
    let active = true;
    void Promise.allSettled([listCalendars(), listTaskLists()]).then(([calendarResult, taskListResult]) => {
      if (!active) return;
      if (calendarResult.status === "fulfilled") {
        setCalendars(calendarResult.value.items);
        setCalendarId((current) => current || calendarResult.value.items.find((item) => item.primary)?.calendar_id || calendarResult.value.items[0]?.calendar_id || "");
      }
      if (taskListResult.status === "fulfilled") {
        setTaskLists(taskListResult.value.items);
        setTaskListId((current) => current || taskListResult.value.items[0]?.tasklist_id || "");
      }
      if (calendarResult.status === "rejected" && taskListResult.status === "rejected") {
        setError("Google 기본 리소스를 불러오지 못했습니다. 연결을 다시 확인해 주세요.");
      }
    });
    return () => { active = false; };
  }, [google.connection_status]);

  const apiProvider = useMemo(() => llm, [llm]);
  const apiAvailable = apiProvider?.validation_status === "VALID";
  const diagnosticsReady = runtime.launcher_status === "READY" && runtime.migration_status === "READY";
  const consentSaved = Boolean(settings?.external_llm_consent);
  const defaultsReady = Boolean(
    settings?.default_calendar_id
    && settings.default_tasklist_id
    && settings.timezone,
  );

  function commandIdFor(operation: string): string {
    let commandId = commandIds.current.get(operation);
    if (!commandId) { commandId = crypto.randomUUID(); commandIds.current.set(operation, commandId); }
    return commandId;
  }

  async function saveConsent(): Promise<void> {
    await run(async () => {
      const response = await updateSettings(commandIdFor("onboarding:consent"), {
        external_llm_consent: consent,
      });
      commandIds.current.delete("onboarding:consent");
      setSettings(response);
    });
  }

  async function connectLLM(): Promise<void> {
    await run(async () => {
      if (apiKey.trim()) {
        await storeLlmCredential(commandIdFor("onboarding:credential"), apiKey, storageMode);
        commandIds.current.delete("onboarding:credential");
      }
      const response = await getLlmCredentialStatus();
      setLLM(response);
      await onRefreshConnections();
    }, true);
  }

  async function completeSetup(): Promise<void> {
    await run(async () => {
      const response = await updateSettings(commandIdFor("onboarding:complete"), {
        default_calendar_id: calendarId.trim(),
        default_tasklist_id: taskListId.trim(),
        timezone: timezone.trim(),
      });
      commandIds.current.delete("onboarding:complete");
      setSettings(response);
      onComplete(response.timezone);
    });
  }

  async function run(operation: () => Promise<void>, clearSecret = false): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await operation();
    } catch (cause) {
      setError(errorMessage(cause, "설정을 완료하지 못했습니다."));
    } finally {
      if (clearSecret) setApiKey("");
      setBusy(false);
    }
  }

  return (
    <main className="startup">
      <section className="startup-card" aria-label="최초 설정">
        <h1>Google Work Agent 시작하기</h1>
        <p>필수 항목을 순서대로 확인합니다. 완료된 항목은 다시 입력하지 않습니다.</p>
        {loading ? <p role="status">설정 상태를 확인하고 있습니다.</p> : null}
        {error ? <p className="status-bad" role="alert">{error}</p> : null}
        <ol className="card-list">
          <ChecklistItem title="Google 로그인과 권한" complete={google.connection_status === "CONNECTED" && google.missing_required_scopes.length === 0}>
            <p>{google.connection_status === "CONNECTED" ? google.display_email : "Google 계정 연결이 필요합니다."}</p>
            {google.connection_status !== "CONNECTED" ? <button className="button-primary" type="button" onClick={onConnectGoogle} disabled={busy}>Google로 로그인</button> : null}
            <button className="button-secondary" type="button" onClick={() => void onRefreshConnections()} disabled={busy}>다시 확인</button>
          </ChecklistItem>
          <ChecklistItem title="개인정보·외부 LLM 전송 동의" complete={consentSaved}>
            <label><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} /> 외부 LLM으로 요청 컨텍스트를 전송하는 데 동의합니다.</label>
            <button className="button-primary" type="button" onClick={() => void saveConsent()} disabled={busy || !consent}>동의 저장</button>
          </ChecklistItem>
          <ChecklistItem title="PC와 Runtime 진단" complete={diagnosticsReady}>
            <p>Launcher {runtime.launcher_status} · 배포 프로필 {runtime.deployment_profile}</p>
          </ChecklistItem>
          <ChecklistItem title="API LLM 연결" complete={apiAvailable}>
            <label>API Key<input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} autoComplete="off" /></label>
            <label>저장 방식<select value={storageMode} onChange={(event) => setStorageMode(event.target.value === "SESSION_ONLY" ? "SESSION_ONLY" : "KEYRING")}><option value="KEYRING">PC에 안전하게 저장</option><option value="SESSION_ONLY">이번 실행에서만 사용</option></select></label>
            <button className="button-primary" type="button" onClick={() => void connectLLM()} disabled={busy}>저장하고 연결 검사</button>
          </ChecklistItem>
          {runtime.deployment_profile === "LOCAL_CAPABLE" ? (
            <ChecklistItem title="Local Runtime 진단" complete={runtime.llm_providers.some((item) => item.provider === "LOCAL_GPU" && item.availability === "READY")}>
              <p>Local GPU {runtime.llm_providers.find((item) => item.provider === "LOCAL_GPU")?.availability ?? "UNAVAILABLE"}. 앱은 모델을 자동 설치하지 않습니다.</p>
            </ChecklistItem>
          ) : null}
          <ChecklistItem title="기본 리소스와 시간대" complete={defaultsReady}>
            <label>기본 Calendar<select value={calendarId} onChange={(event) => setCalendarId(event.target.value)}><option value="">선택</option>{calendars.map((item) => <option key={item.calendar_id} value={item.calendar_id}>{item.title}{item.primary ? " (기본)" : ""}</option>)}</select></label>
            <label>기본 Task List<select value={taskListId} onChange={(event) => setTaskListId(event.target.value)}><option value="">선택</option>{taskLists.map((item) => <option key={item.tasklist_id} value={item.tasklist_id}>{item.title}</option>)}</select></label>
            <label>Timezone<input value={timezone} onChange={(event) => setTimezone(event.target.value)} /></label>
            <button className="button-primary" type="button" onClick={() => void completeSetup()} disabled={busy || google.connection_status !== "CONNECTED" || google.missing_required_scopes.length > 0 || !consentSaved || !diagnosticsReady || !apiAvailable || !calendarId.trim() || !taskListId.trim() || !timezone.trim()}>설정 완료하고 시작</button>
          </ChecklistItem>
        </ol>
      </section>
    </main>
  );
}

function ChecklistItem({ title, complete, children }: { title: string; complete: boolean; children: ReactNode }): JSX.Element {
  return <li className="info-card"><strong>{complete ? "완료" : "필요"} · {title}</strong>{complete ? null : <div>{children}</div>}</li>;
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiClientError ? error.message : fallback;
}
