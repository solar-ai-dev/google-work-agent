import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  getCurrentAccount,
  getGoogleConnection,
  getLive,
  getReady,
  getRuntime,
  getSettings,
} from "../api";
import { ApiClientError } from "../api/client";
import {
  API_CONTRACT_VERSION,
  type CurrentGoogleAccountResponse,
  type GoogleConnectionResponse,
  type RuntimeSummary,
} from "../api/contract";
import { StartupCheckScreen, type StartupCheckState } from "../features/diagnostics/startup_check";
import { ApiCompatibilityGate, type ApiCompatibility } from "./api_compatibility_gate";
import { bootstrapLocalSession, readBootstrapFragment } from "./session_bootstrap";

export type StartupFlowContext = {
  runtime: RuntimeSummary;
  google: GoogleConnectionResponse;
  currentAccount: CurrentGoogleAccountResponse["account"];
  calendarTimezone: string;
  setupCompleted: boolean;
};

type Props = {
  children: (context: StartupFlowContext) => ReactNode;
};

const INITIAL_STATE: StartupCheckState = {
  phase: "boot",
  status: "idle",
  message: "시작 검사를 준비하고 있습니다.",
  checks: [],
};

export function StartupFlow({ children }: Props): JSX.Element {
  const [state, setState] = useState<StartupCheckState>(INITIAL_STATE);
  const [compatibility, setCompatibility] = useState<ApiCompatibility>("PENDING");
  const [serverApiContractVersion, setServerApiContractVersion] = useState<string | null>(null);
  const [context, setContext] = useState<StartupFlowContext | null>(null);
  const startupPromiseRef = useRef<Promise<void> | null>(null);

  const runStartup = useCallback(async (): Promise<void> => {
    const bootstrapFragment = readBootstrapFragment(window.location.hash);
    setContext(null);
    setCompatibility("PENDING");
    setState({
      phase: "checks",
      status: "loading",
      message: "로컬 서비스 상태를 확인하고 있습니다.",
      checks: [],
    });
    try {
      const live = await getLive();
      setServerApiContractVersion(live.api_contract_version);
      if (live.api_contract_version !== API_CONTRACT_VERSION) {
        setCompatibility("INCOMPATIBLE");
        setState({
          phase: "compatibility",
          status: "error",
          message: "Frontend와 Local API 버전이 호환되지 않습니다.",
          checks: [],
          error: "앱을 업데이트한 뒤 다시 시작해 주세요.",
        });
        return;
      }

      const ready = await getReady();
      if (ready.api_contract_version !== API_CONTRACT_VERSION) {
        setServerApiContractVersion(ready.api_contract_version);
        setCompatibility("INCOMPATIBLE");
        setState({
          phase: "compatibility",
          status: "error",
          message: "Frontend와 Local API 준비 계약이 호환되지 않습니다.",
          checks: ready.checks,
          error: "앱을 업데이트한 뒤 다시 시작해 주세요.",
        });
        return;
      }
      if (ready.status !== "READY") {
        setCompatibility("UNAVAILABLE");
        setState({
          phase: "readiness",
          status: "error",
          message: ready.status === "SAFE_MODE"
            ? "Local Service가 안전 모드로 실행 중입니다."
            : "Local Service가 아직 준비되지 않았습니다.",
          checks: ready.checks,
          error: "검사 상세를 확인하고 다시 시도해 주세요.",
        });
        return;
      }
      setState({
        phase: "session",
        status: "loading",
        message: bootstrapFragment ? "로컬 세션을 수립하고 있습니다." : "기존 로컬 세션을 확인하고 있습니다.",
        checks: ready.checks,
      });

      if (bootstrapFragment !== null) {
        const bootstrap = await bootstrapLocalSession(bootstrapFragment);
        setServerApiContractVersion(bootstrap.api_contract_version);
        if (
          !bootstrap.session_established
          || bootstrap.compatibility !== "COMPATIBLE"
          || bootstrap.api_contract_version !== API_CONTRACT_VERSION
        ) {
          setCompatibility("INCOMPATIBLE");
          setState({
            phase: "compatibility",
            status: "error",
            message: "Local API 호환성 확인에 실패했습니다.",
            checks: ready.checks,
            error: "호환되는 앱 버전으로 다시 시작해 주세요.",
          });
          return;
        }
      }

      setCompatibility("COMPATIBLE");
      setState((current) => ({
        ...current,
        phase: "runtime",
        message: "보호된 실행 상태를 불러오고 있습니다.",
      }));
      const [runtime, google, settings, firstAccount] = await Promise.all([
        getRuntime(),
        getGoogleConnection(),
        getSettings(),
        getCurrentAccount(),
      ]);
      const account = google.connection_status === "CONNECTED" && firstAccount.account === null
        ? (await getCurrentAccount()).account
        : firstAccount.account;
      const setupCompleted = Boolean(
        settings.default_calendar_id
        && settings.default_tasklist_id
        && settings.timezone,
      );
      setContext({
        runtime,
        google,
        currentAccount: account,
        calendarTimezone: settings.timezone,
        setupCompleted,
      });
      setState({
        phase: "ready",
        status: "ready",
        message: "UI를 준비했습니다.",
        checks: ready.checks,
      });
    } catch (error) {
      setCompatibility((current) => current === "INCOMPATIBLE" ? current : "UNAVAILABLE");
      setState({
        phase: "failed",
        status: "error",
        message: "시작 검사를 완료하지 못했습니다.",
        checks: [],
        error: error instanceof ApiClientError ? error.message : "앱을 다시 열어 주세요.",
      });
    }
  }, []);

  useEffect(() => {
    if (startupPromiseRef.current === null) {
      startupPromiseRef.current = runStartup();
    }
  }, [runStartup]);

  const fallback = <StartupCheckScreen state={state} onRetry={() => void runStartup()} />;
  return (
    <ApiCompatibilityGate
      compatibility={compatibility}
      serverApiContractVersion={serverApiContractVersion}
      fallback={fallback}
    >
      {state.status === "ready" && context !== null ? children(context) : fallback}
    </ApiCompatibilityGate>
  );
}
