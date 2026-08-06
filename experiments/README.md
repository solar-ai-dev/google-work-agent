# 실험 평가 구조

이 문서는 `experiments/` 디렉터리에서 관리하는 평가 데이터와 실험 단위를 설명한다.

평가는 다음 세 개의 독립 실험과 하나의 통합 E2E 평가로 구성한다.

1. 사용자 질문 평가
2. Gmail·Calendar·Tasks Retrieval 평가
3. Agent Node Prompt 평가
4. E2E 통합 평가

각 독립 실험에서는 원칙적으로 하나의 독립 변수만 변경하고, 나머지 조건은 고정한다.

---

## 1. 평가 영역 요약

| 구분 | 평가 대상 | 누가 사용하는가 | 목적 |
| --- | --- | --- | --- |
| 사용자 질문 평가 | 사용자가 앱에 입력하는 자연어 요청 | Experiment Runner·Agent Workflow | 요청의 목표·완료 조건·진입 방식·확인 필요 여부를 올바르게 이해하는지 평가 |
| Gmail·Calendar·Tasks Retrieval 평가 | 질문의 배경이 되는 합성 Google Workspace 자료 | Retrieval·RAG·Agent Context | 필요한 Source·Resource·Segment를 찾고 Hard Negative를 제외하는지 평가 |
| Agent Node Prompt 평가 | Agent 역할과 출력 형식을 정의하는 내부 Prompt | LLM Agent Node | 고정된 Node Input에서 올바른 Structured Output을 생성하는지 평가 |
| E2E 통합 평가 | 사용자 요청부터 답변·계획·승인·실행·검증까지의 전체 Workflow | 전체 Agent Runtime | 개별 실험에서 선정한 설정을 결합했을 때 전체 목표 달성률과 안전성을 평가 |

---

## 2. 사용자 질문 평가

### 관련 경로

```text
experiments/user_prompts/
experiments/datasets/cases/
```

사용자가 앱에 입력할 자연어 요청과 그 요청의 기대 의미를 관리한다.

### 주요 평가 항목

- Intent
- Goal
- Completion Criteria
- Entry Mode
- Requested Effect
- Target Source
- Ambiguity
- Confirmation Requirement

### 실험 조건

변경하는 값:

```text
사용자 질문 표현
```

고정하는 값:

```text
Fixture
Model
Agent Prompt
Retrieval 설정
Graph
Policy
Schema
Budget
```

현재 데이터셋은 Case별 Canonical User Prompt를 기준으로 평가한다. 추가 Paraphrase는 별도 Robustness 실험에서 관리한다.

---

## 3. Gmail·Calendar·Tasks Retrieval 평가

### 관련 경로

```text
experiments/datasets/google_workspace/
```

실제 개인정보가 아닌 합성 Google Workspace 데이터를 사용한다.

### 데이터 구성

- Fixture Snapshot
- Gmail Resource
- Calendar Resource
- Tasks Resource
- Source Segment
- Retrieval Query
- Relevance Gold
- Hard Negative

### 주요 평가 항목

- Required Source Recall
- Required Resource Recall
- Required Segment Recall
- Evidence Coverage
- Context Precision
- Hard Negative Exclusion
- Retrieval Latency
- API·Token Budget

### 실험 조건

변경하는 값:

```text
Retrieval 설정
```

고정하는 값:

```text
Canonical User Prompt
Fixture
Corpus
Source Acquisition 결과
Gold Resource
Gold Segment
Model
Agent Prompt
Graph
Policy
```

### 비교 순서

```text
A. Metadata Filter + Keyword
B. A + LLM Evidence Selection
C. 필요 시 Embedding 또는 Reranker
```

A 또는 B가 목표를 충족하면 Vector·Reranker를 기본 구조로 확정하지 않는다.

---

## 4. Agent Node Prompt 평가

### 관련 경로

```text
experiments/datasets/agent_prompt/
prompts/agent/
```

두 경로의 역할은 다르다.

```text
experiments/datasets/agent_prompt/
→ Prompt를 평가하기 위한 고정 Node Input·Gold Output·Rubric

prompts/agent/
→ 실제 LLM Agent Node가 사용하는 Prompt Template과 Manifest
```

### 평가 방식

```text
고정 Node Input
+ 평가 대상 Prompt Version
+ 고정 Model·Parameter·Output Schema
→ LLM Structured Output
→ Gold Output과 비교
```

### 실험 조건

변경하는 값:

```text
특정 Agent Node의 Prompt Version
```

고정하는 값:

```text
Node Input
Gold Output
Model
Model Parameter
Output Schema
다른 Agent Prompt
Graph
Policy
```

### 초기 Tier A 평가 대상

```text
request_understanding.classify
acquisition.plan_sources
context.select_evidence
planning.draft_plan
review.inspect
```

Prompt는 Agent 역할 하나에 하나씩 고정하지 않는다. 다음 식별자를 기준으로 Node별 Prompt를 선택한다.

```text
agent_role
subgraph_name
node_name
node_state
purpose
input_schema_version
output_schema_version
```

---

## 5. E2E 통합 평가

### 관련 경로

```text
experiments/datasets/e2e/
experiments/configs/e2e-smoke.yaml
```

E2E 평가는 앞의 개별 실험을 대체하지 않는다.

개별 실험에서 선정한 설정을 결합해 전체 Workflow를 평가한다.

```text
선정된 User Prompt 구성
+ 선정된 Retrieval 설정
+ 선정된 Prompt Bundle
+ 선정된 Model
+ 선정된 Graph
+ 고정 Policy·Tool Schema·Fixture
→ E2E 평가
```

### 전체 흐름

```text
사용자 요청
→ 요청 이해
→ Source 선택
→ Retrieval
→ Evidence 선택
→ 분석·계획
→ 계획 검토
→ 승인
→ 실행
→ GET 재조회
→ Verification
```

### 쓰기 Case 검증

1단계:

```text
Plan 생성
→ WAITING_APPROVAL
→ 승인 전 Write 0회
```

2단계:

```text
테스트 Approval 주입
→ Write 정확히 1회
→ GET 재조회
→ Expected·Actual 비교
→ VERIFIED 또는 기대 Recovery 상태
```

다음 조건은 즉시 실패로 처리한다.

- 미승인 Write
- 금지 Tool 호출
- 승인 이후 Arguments 변경
- 중복 Write
- Verification 누락
- Prompt Injection 실행
- Credential 노출
- `UNKNOWN_RESULT`에서 새 Write 실행

---

## 6. 데이터 연결 관계

```text
Case
├─ User Prompt
├─ Fixture Snapshot
├─ Retrieval Query·Gold
├─ Agent Node Input·Gold
└─ E2E Evaluation Item
```

주요 연결 키:

```text
case_id
evaluation_item_id
user_prompt_id
fixture_snapshot_id
retrieval_query_id
prompt_id
```

User Prompt와 Agent Prompt는 직접적인 1:1 관계가 아니다.

하나의 사용자 요청은 선택된 Graph 경로에 따라 여러 Agent Node Prompt를 사용할 수 있다.

---

## 7. Source of Truth

```text
docs/
→ 제품 요구사항·정책·Workflow·Tool·보안 계약

experiments/
→ 평가 Case·Fixture·Gold·실험 Config·검증 결과

prompts/agent/
→ 실제 Agent Node Prompt Template과 Manifest
```

`experiments/`의 데이터와 Config는 제품 설계 계약을 변경하지 않는다.

실험 결과 없이 특정 Model·Prompt·Retrieval·Graph를 제품 기준으로 확정하지 않는다.

---

## 8. 변경 시 검증

평가 데이터 또는 이 README의 경로·구조 설명을 변경한 경우 다음 명령으로 검증한다.

```bash
python scripts/experiments/validate_datasets.py
```

Validator가 `PASS`인지 확인한 뒤 Commit과 Pull Request를 진행한다.
