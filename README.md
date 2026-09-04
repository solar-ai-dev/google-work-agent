# Google Work Agent

Google Work Agent는 로컬 PC에서 실행되는 단일 사용자 Google Workspace 업무 Agent입니다. FastAPI API, React UI, LangGraph workflow, SQLite Domain Store, 로컬 MCP Connector, API/Local LLM runtime을 하나의 제품 composition으로 연결합니다. 승인·Claim·Write·검증·복구는 결정적 Application/Domain 경계가 소유하며 Agent/LLM이 최종 판정하지 않습니다.

## 요구 환경

- Windows 11 x64
- CPython 3.12
- Node.js 20 이상과 npm

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r config\requirements-cpu.txt
.\.venv\Scripts\python.exe -m pip install -e .
npm --prefix frontend ci
npm --prefix frontend run build
```

GPU/Local Model 검증이 필요한 경우 `config\requirements-gpu.txt` 환경을 별도로 사용할 수 있습니다. Product Decision artifact가 없는 개발 baseline에서는 API LLM을 연결해 smoke할 수 있습니다.

## 개발 Product 실행

개발 launcher도 설치 제품과 같은 `create_app → DeferredApiContainer → build_production_runtime` composition과 loopback·Host/Origin·one-time bootstrap·Local Session·readiness·shutdown 경계를 사용합니다.

```powershell
.\.venv\Scripts\python.exe -m launcher.development_entrypoint `
  --runtime-root .\runtime\development `
  --host 127.0.0.1 `
  --port 0
```

`--port 0`은 안전한 loopback dynamic port를 사용합니다. 준비가 끝나면 브라우저가 one-time bootstrap fragment로 열리고, UI는 같은 FastAPI origin의 `/`에서 제공됩니다. bootstrap secret은 일반 로그에 출력되지 않습니다.

브라우저 자동화나 Codex에서 URL을 받아야 하면 descriptor를 사용합니다.

```powershell
.\.venv\Scripts\python.exe -m launcher.development_entrypoint `
  --runtime-root .\runtime\development `
  --port 0 `
  --no-browser `
  --launch-descriptor .\.runtime\development-launch.json
```

Descriptor에는 `base_url`, one-time `bootstrap_url`, `service_instance_id`, `process_id`, `readiness_state`만 기록되며 현재 사용자 전용 권한을 적용합니다. 정상 종료 시 자동 삭제됩니다. `bootstrap_url`은 secret이므로 공유하거나 로그에 복사하지 마세요.

Readiness는 descriptor의 `base_url`로 확인합니다.

```powershell
$launch = Get-Content .\.runtime\development-launch.json | ConvertFrom-Json
Invoke-RestMethod "$($launch.base_url)/health/ready"
```

개발 baseline Prompt는 아직 실험 승격 전이므로 readiness의 `prompt_activation` check가 `READY / UNVALIDATED_BASELINE`으로 표시됩니다. 이는 제품 wiring smoke 가능 상태이지 Prompt 품질 또는 Release 승인 상태가 아닙니다.

## LLM과 Google 연결

첫 UI 진입 후 설정에서 Gemini API Key를 연결하고 API LLM 사용 및 외부 전송 동의를 설정합니다. Development launcher의 LLM credential은 process memory에만 보관되며 종료 후 사라집니다. Local Model은 signed Model Manifest와 Product Decision을 갖춘 `LOCAL_CAPABLE` release에서만 활성화됩니다.

- 첫 실행 완료와 모든 Agent Run에는 Google OAuth 연결 및 필수 Scope 동의가 필요합니다.
- Gmail·Calendar·Tasks 조회 또는 변경은 연결된 Google 계정 권한을 사용합니다.
- 모든 Write는 Canonical Approval 이후 Claim/Execution Attempt/Connector Write/Verification 순서를 거칩니다.

## 검증

```powershell
.\.venv\Scripts\python.exe -m pytest --collect-only -q
.\.venv\Scripts\python.exe -m pytest -q
$env:GWA_ARCHITECTURE_FINAL_CUTOVER = "1"
.\.venv\Scripts\python.exe -m pytest tests\architecture -q
.\.venv\Scripts\ruff.exe check src tests launcher release scripts
.\.venv\Scripts\mypy.exe src tests launcher release scripts
.\.venv\Scripts\python.exe -m compileall -q src launcher release scripts tests

npm --prefix frontend test -- --run
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend run build
```

`tests/e2e`와 `tests/evaluation`의 deterministic fake Provider/MCP 실행은 workflow·계약·external-effect 회귀를 검증하지만 실제 LLM 품질 증거가 아닙니다. 실제 Product E2E는 development launcher로 UI에 접속해 실제 LLM credential과 필요한 Google OAuth를 연결한 뒤 별도로 수행합니다.

## Prompt/Model 현재 상태

Canonical Prompt source 21개는 실험 전 baseline이며 manifest 상태는 모두 `DRAFT`입니다. `EXPLICIT_DEVELOPMENT`의 `DEVELOPMENT_SMOKE`에서만 실행할 수 있고, signed Release는 실제 DEV/HOLDOUT/Safety/승인 evidence artifact가 완전한 `RUNTIME_ACTIVE` Prompt만 패키징·실행합니다. 최종 Provider/Model/Prompt bundle 선택은 실험 완료 전까지 유보됩니다.

설계 Authority와 읽기 순서는 `docs/canonical/00-project-source-guide.md`에서 시작합니다.
