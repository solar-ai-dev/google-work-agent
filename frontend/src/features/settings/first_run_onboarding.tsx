import { useEffect, useRef, useState, type ReactNode } from "react";
import { ApiClientError } from "../../api/client";
import type { RuntimeSummary } from "../diagnostics";
import type { GoogleConnection } from "./api/google_connection_operations";
import { getSettings, type SettingsView } from "./api/get_settings";
import { getLlmCredentialStatus, storeLlmCredential, type LlmCredentialStatus } from "./api/llm_credential_operations";
import { updateRuntimeMode } from "./api/update_runtime_mode";
import { updateSettings } from "./api/update_settings";

type Props = {
  runtime: RuntimeSummary;
  google: GoogleConnection;
  statusLine: string;
  onConnectGoogle: () => void;
  onRefreshConnections: () => Promise<void>;
  onComplete: () => void;
};

export function FirstRunOnboardingScreen({
  runtime,
  google,
  statusLine,
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
  const commandIds = useRef(new Map<string, string>());

  useEffect(() => {
    let active = true;
    void Promise.all([getSettings(), getLlmCredentialStatus()])
      .then(([settingsResponse, llmResponse]) => {
        if (!active) return;
        setSettings(settingsResponse);
        setLLM(llmResponse);
        setConsent(settingsResponse.external_llm_consent);
      })
      .catch((cause: unknown) => {
        if (active) setError(errorMessage(cause, "설정 상태를 불러오지 못했습니다."));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  const apiAvailable = llm?.validation_status === "VALID";
  const localProvider = runtime.llm_providers.find((item) => item.provider === "LOCAL_GPU");
  const selectedLocalModel = runtime.local_models.find(
    (item) => item.selected && item.installed && item.approved,
  );
  const localAvailable = Boolean(
    selectedLocalModel
    && localProvider?.availability === "READY",
  );
  const llmReady = localAvailable || apiAvailable;
  const diagnosticsReady = runtime.launcher_status === "READY" && runtime.migration_status === "READY";
  const consentSaved = Boolean(settings?.external_llm_consent);

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
      const updated = await updateSettings(commandIdFor("onboarding:api-mode"), {
        preferred_llm_mode: "AUTO",
      });
      commandIds.current.delete("onboarding:api-mode");
      await updateRuntimeMode(commandIdFor("onboarding:runtime:auto"), "AUTO");
      commandIds.current.delete("onboarding:runtime:auto");
      setSettings(updated);
      await onRefreshConnections();
    }, true);
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
        <p role="status" aria-live="polite">{statusLine}</p>
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
          <ChecklistItem title="PC와 실행 환경 진단" complete={diagnosticsReady}>
            <p>{diagnosticsReady ? "실행 환경이 준비되었습니다." : "실행 환경 점검이 필요합니다."}</p>
          </ChecklistItem>
          <ChecklistItem title="LLM 자동 연결" complete={llmReady}>
            <p>시스템이 로컬 LLM을 우선 확인하고 사용할 수 없으면 구성된 API LLM을 사용합니다.</p>
            <label>API 키<input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} autoComplete="off" /></label>
            <label>저장 방식<select value={storageMode} onChange={(event) => setStorageMode(event.target.value === "SESSION_ONLY" ? "SESSION_ONLY" : "KEYRING")}><option value="KEYRING">PC에 안전하게 저장</option><option value="SESSION_ONLY">이번 실행에서만 사용</option></select></label>
            <button className="button-primary" type="button" onClick={() => void connectLLM()} disabled={busy || !apiKey.trim()}>API 키 저장 후 자동 연결</button>
          </ChecklistItem>
          <ChecklistItem title="시작 준비" complete={false}>
            <button className="button-primary" type="button" onClick={onComplete} disabled={busy || google.connection_status !== "CONNECTED" || google.missing_required_scopes.length > 0 || !consentSaved || !diagnosticsReady || !llmReady}>설정 완료하고 시작</button>
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
