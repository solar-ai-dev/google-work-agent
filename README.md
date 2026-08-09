# Google Work Agent

Google Work Agent는 사용자 로컬 PC에서 실행하는 단일 사용자용 Google 업무 Agent입니다.

## 개발 환경

- 공식 Python 버전: Python 3.12.x
- 기본 검증 환경: `.venv-cpu`
- GPU 관련 검증은 이후 단계에서 `.venv-gpu`를 사용합니다.

PowerShell에서 CPU 환경을 활성화합니다.

```powershell
.\.venv-cpu\Scripts\Activate.ps1
```

PowerShell에서 GPU 환경을 활성화합니다.

```powershell
.\.venv-gpu\Scripts\Activate.ps1
```

의존성 설치 기준은 `pyproject.toml`이 아니라 기존 requirements 파일입니다.

```powershell
.\.venv-cpu\Scripts\python.exe -m pip install -r config\requirements-cpu.txt
.\.venv-gpu\Scripts\python.exe -m pip install -r config\requirements-gpu.txt
```

Colab 실험 환경은 `config/requirements-colab.txt`를 기준으로 합니다.

## 개발용 Local Service 실행

Terminal 1에서 FastAPI Local Service를 loopback으로 실행합니다.

```powershell
.\.venv-gpu\Scripts\python.exe -m google_work_agent.launcher.dev --host 127.0.0.1 --port 8000
```

실행 직후 출력되는 one-time bootstrap URL을 복사합니다. Terminal 2에서 Vite를 실행한 뒤,
출력된 fragment를 붙인 `http://127.0.0.1:5173/` URL을 브라우저로 엽니다.

```powershell
Set-Location frontend
npm run dev
```

Vite는 `/api`와 `/health`를 기본 `http://127.0.0.1:8000`으로 proxy합니다. Service port를
변경했다면 Terminal 2에서 `VITE_API_PROXY_TARGET`에 같은 loopback 주소를 설정합니다.

## 검증 명령

```powershell
.\.venv-cpu\Scripts\python.exe -m pip check
.\.venv-cpu\Scripts\python.exe -m pytest tests\unit -q
.\.venv-cpu\Scripts\python.exe -m pytest tests\integration -q
.\.venv-cpu\Scripts\python.exe -m pytest -q
.\.venv-cpu\Scripts\python.exe -m ruff check src tests scripts
.\.venv-cpu\Scripts\python.exe -m ruff format --check src tests scripts
.\.venv-cpu\Scripts\python.exe -m mypy src tests
```

패키지 import 확인이 필요하면 editable install 후 실행합니다.

```powershell
.\.venv-cpu\Scripts\python.exe -m pip install -e .
.\.venv-cpu\Scripts\python.exe -c "import google_work_agent; print(google_work_agent.__version__)"
```

## 현재 구현 단계

현재 단계는 M1-01 Python Project Skeleton입니다. 패키지 구조, 테스트 진입점,
Ruff, mypy, pytest 설정만 준비되어 있습니다.

아직 Domain 상태 전이, SQLite, Repository, FastAPI, LangGraph, LLM, MCP, Google API,
Fixture는 제품 코드에 연결되어 있지 않습니다.

## 설계 문서

설계 기준은 `docs/` 아래 문서를 따릅니다. 시작 문서는
`docs/00-CODE-AGENT-START-HERE.md`입니다.
