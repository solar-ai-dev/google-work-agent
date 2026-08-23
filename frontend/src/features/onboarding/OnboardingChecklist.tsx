import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  getLLMConnection,
  getSettings,
  patchSettings,
  storeLLMApiKey,
  testLLMConnection,
} from "../../api";
import { ApiClientError } from "../../api/client";
import type { GoogleConnectionResponse, RuntimeSummary } from "../../api/contract";

type Props = {
  runtime: RuntimeSummary;
  google: GoogleConnectionResponse;
  onConnectGoogle: () => void;
  onRefreshConnections: () => Promise<void>;
  onComplete: (timezone: string) => void;
};

export function OnboardingChecklist({
  runtime,
  google,
  onConnectGoogle,
  onRefreshConnections,
  onComplete,
}: Props): JSX.Element {
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [llm, setLLM] = useState<Record<string, unknown>>({});
  const [consent, setConsent] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [storageMode, setStorageMode] = useState<"KEYRING" | "SESSION_MEMORY">("KEYRING");
  const [calendarId, setCalendarId] = useState("primary");
  const [taskListId, setTaskListId] = useState("@default");
  const [timezone, setTimezone] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Seoul");

  useEffect(() => {
    let active = true;
    void Promise.all([getSettings(), getLLMConnection()])
      .then(([settingsResponse, llmResponse]) => {
        if (!active) return;
        const loadedSettings = asRecord(settingsResponse.settings);
        setSettings(loadedSettings);
        setLLM(asRecord(llmResponse.llm));
        setConsent(Boolean(loadedSettings.external_llm_consent));
        setCalendarId(stringValue(loadedSettings.default_calendar_id) ?? "primary");
        setTaskListId(stringValue(loadedSettings.default_tasklist_id) ?? "@default");
        setTimezone(stringValue(loadedSettings.timezone) ?? "Asia/Seoul");
      })
      .catch((cause: unknown) => {
        if (active) setError(errorMessage(cause, "설정 상태를 불러오지 못했습니다."));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  const apiProvider = useMemo(() => asRecord(llm.api_provider), [llm]);
  const apiAvailable = apiProvider.availability === "AVAILABLE";
  const diagnosticsReady = runtime.mcp === "READY";
  const consentSaved = Boolean(settings.external_llm_consent);
  const defaultsReady = Boolean(
    stringValue(settings.default_calendar_id)
    && stringValue(settings.default_tasklist_id)
    && stringValue(settings.timezone),
  );

  async function saveConsent(): Promise<void> {
    await run(async () => {
      const response = await patchSettings({
        command_id: `onboarding-consent-${Date.now()}`,
        external_llm_consent: consent,
      });
      setSettings(asRecord(response.settings));
    });
  }

  async function connectLLM(): Promise<void> {
    await run(async () => {
      if (apiKey.trim()) {
        await storeLLMApiKey({ api_key: apiKey, storage_mode: storageMode });
        setApiKey("");
      }
      const response = await testLLMConnection();
      setLLM(asRecord(response.llm));
      await onRefreshConnections();
    });
  }

  async function completeSetup(): Promise<void> {
    await run(async () => {
      const response = await patchSettings({
        command_id: `onboarding-complete-${Date.now()}`,
        setup_completed: true,
        default_calendar_id: calendarId.trim(),
        default_tasklist_id: taskListId.trim(),
        timezone: timezone.trim(),
      });
      const saved = asRecord(response.settings);
      setSettings(saved);
      onComplete(stringValue(saved.timezone) ?? timezone.trim());
    });
  }

  async function run(operation: () => Promise<void>): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await operation();
    } catch (cause) {
      setError(errorMessage(cause, "설정을 완료하지 못했습니다."));
    } finally {
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
          <ChecklistItem title="Google 로그인과 권한" complete={google.connected && google.missing_scopes.length === 0}>
            <p>{google.connected ? google.account_email : "Google 계정 연결이 필요합니다."}</p>
            {!google.connected ? <button className="button-primary" type="button" onClick={onConnectGoogle} disabled={busy}>Google로 로그인</button> : null}
            <button className="button-secondary" type="button" onClick={() => void onRefreshConnections()} disabled={busy}>다시 확인</button>
          </ChecklistItem>
          <ChecklistItem title="개인정보·외부 LLM 전송 동의" complete={consentSaved}>
            <label><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} /> 외부 LLM으로 요청 컨텍스트를 전송하는 데 동의합니다.</label>
            <button className="button-primary" type="button" onClick={() => void saveConsent()} disabled={busy || !consent}>동의 저장</button>
          </ChecklistItem>
          <ChecklistItem title="PC와 Runtime 진단" complete={diagnosticsReady}>
            <p>MCP {runtime.mcp} · 배포 프로필 {runtime.deployment_profile}</p>
          </ChecklistItem>
          <ChecklistItem title="API LLM 연결" complete={apiAvailable}>
            <label>API Key<input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} autoComplete="off" /></label>
            <label>저장 방식<select value={storageMode} onChange={(event) => setStorageMode(event.target.value === "SESSION_MEMORY" ? "SESSION_MEMORY" : "KEYRING")}><option value="KEYRING">PC에 안전하게 저장</option><option value="SESSION_MEMORY">이번 실행에서만 사용</option></select></label>
            <button className="button-primary" type="button" onClick={() => void connectLLM()} disabled={busy}>저장하고 연결 검사</button>
          </ChecklistItem>
          {runtime.deployment_profile === "LOCAL_CAPABLE" ? (
            <ChecklistItem title="Local Runtime 진단" complete={runtime.ollama === "AVAILABLE"}>
              <p>Ollama {runtime.ollama}. 앱은 Ollama나 모델을 자동 설치하지 않습니다.</p>
            </ChecklistItem>
          ) : null}
          <ChecklistItem title="기본 리소스와 시간대" complete={defaultsReady}>
            <label>기본 Calendar<input value={calendarId} onChange={(event) => setCalendarId(event.target.value)} /></label>
            <label>기본 Task List<input value={taskListId} onChange={(event) => setTaskListId(event.target.value)} /></label>
            <label>Timezone<input value={timezone} onChange={(event) => setTimezone(event.target.value)} /></label>
            <button className="button-primary" type="button" onClick={() => void completeSetup()} disabled={busy || !google.connected || google.missing_scopes.length > 0 || !consentSaved || !diagnosticsReady || !apiAvailable || !calendarId.trim() || !taskListId.trim() || !timezone.trim()}>설정 완료하고 시작</button>
          </ChecklistItem>
        </ol>
      </section>
    </main>
  );
}

function ChecklistItem({ title, complete, children }: { title: string; complete: boolean; children: ReactNode }): JSX.Element {
  return <li className="info-card"><strong>{complete ? "완료" : "필요"} · {title}</strong>{complete ? null : <div>{children}</div>}</li>;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiClientError ? error.message : fallback;
}
