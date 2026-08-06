# Google Work Agent · Colab Experiment Guide

## 결론

Colab에서도 Repository 코드를 사용할 수 있고 LangGraph도 실행할 수 있다.
로컬 PC 파일이 자동으로 보이지 않을 뿐이며, Git Repository를 clone한 뒤 같은 Python package와 실험 Runner를 import하면 된다.

## 실험별 LangGraph 필요 여부

| 실험 | LangGraph 필수 | Colab 가능 | 실행 단위 |
|---|---:|---:|---|
| API/Gemini 모델 Screening | 아니오 | 가능 | LLM Provider Adapter + Evaluation Item |
| Prompt·Structured Output | 아니오 | 가능 | PromptRef + Input/Output Schema |
| Retrieval Baseline | 아니오 | 가능 | 고정 Acquisition Result + Retriever 함수 |
| Workflow Ablation | 예 | 가능 | SINGLE / THREE_STAGE / SIX_ROLE Graph |
| Windows Launcher·Local Session | 해당 없음 | 제외 | Windows 통합 테스트에서 수행 |
| 실제 Google OAuth·MCP Write | 해당 없음 | 기본 제외 | 로컬 Test User Lane에서 수행 |
| Local sLLM 후보 Screening | 아니오/선택 | 가능 | HF Transformers 실험 Adapter |
| 제품 Local 모델 최종 검증 | 예 | Colab 결과만으로 불가 | 실제 Ollama GPU 환경에서 재실행 |

## 코드 재사용 경계

Colab에서 그대로 사용:

- Versioned Pydantic Schema
- Prompt Registry와 PromptRef
- Node 함수와 Graph Profile
- FakeGoogleGateway와 합성 Fixture
- Evaluation Runner와 Metric
- Dataset·Gold·User Prompt

Colab에서 실행하지 않음:

- Windows Launcher
- Browser bootstrap과 same-origin Local Session
- Windows OS Keyring 실제 Adapter
- 설치형 MCP child-process 수명주기
- 공개 배포용 OAuth loopback 통합
- Installer·Code Signing·Backup 경로 테스트

## 권장 실행 절차

```python
# 1. Repository clone
!git clone <REPOSITORY_URL> google-work-agent
%cd google-work-agent

# 2. Colab 의존성 설치
!python -m pip install -r requirements-colab.txt

# 3. Repository가 Python package 구조를 가진 뒤
!python -m pip install -e . --no-deps
```

API Key는 Notebook 셀이나 Git 파일에 직접 기록하지 않는다. Colab Secret 기능에서 읽어 Provider Adapter에 전달한다.

## Local Model 실험 계약

Colab의 Hugging Face 실행은 후보를 줄이는 Screening Lane이다.
제품 Runtime은 Ollama로 고정되어 있으므로 최종 후보는 동일한 다음 조건으로 실제 Ollama 환경에서 다시 실행한다.

```text
model_id
model_revision
prompt_bundle_version
graph_version
fixture_snapshot_hash
quantization
context_window
structured_output_schema
```

실험 결과에는 `runtime_backend=HF_TRANSFORMERS` 또는 `runtime_backend=OLLAMA`를 반드시 기록한다. 서로 다른 Backend 결과를 동일 실행으로 합치지 않는다.

## 제품 Runtime 잠금 규칙

```text
API_ONLY build
→ LOCAL_GPU와 AUTO_LOCAL 옵션 비노출

LOCAL_CAPABLE build
→ HardwareProbe
→ 지원 GPU + Ollama + 승인 Model 모두 통과
   → LOCAL_GPU/AUTO 활성화
→ 하나라도 실패
   → API_LLM만 활성화
```

Requirements 분리는 배포 의존성을 줄이는 수단이다. 실제 기능 잠금은 Signed Build Profile과 Runtime HardwareProbe가 결정해야 한다.
