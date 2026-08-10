# 00-B. 평가·실험 전략과 선택 이유

> **문서 성격:** 설명 문서. 실험 권위 계약은 `13. 평가·실험 설계서`, Prompt·Failure 정규화는 `15`, 제품 회귀·안전 검증은 `12`, 관측 계약은 `11`이 소유한다.

## 1. 한 문장으로 설명하면

Google Work Agent의 평가는 **안전을 먼저 Hard Gate로 통과시킨 뒤 업무 성공을 비교하고, 실패 원인을 Process로 분해한 다음, 품질을 만족한 후보끼리 비용·지연·반복성을 비교해 제품 결정을 내리는 구조**다.

```text
Dataset·Grader Integrity
→ Safety / Write Integrity Gate
→ Business Task Success
→ Process 원인 분석
→ Efficiency 비교
→ Reliability / Holdout / Stress
→ Product Decision
```

## 2. 왜 실험이 핵심인가

이 프로젝트에는 여러 선택지가 있다.

- Model·Runtime
- Prompt·Structured Output·Repair
- Source Acquisition 전략과 Read Budget
- Evidence 선택과 Context Budget
- SINGLE / THREE / SIX Graph Profile
- Conditional Agent Skip
- Review Agent 유무

이를 “그럴듯해 보인다”는 이유로 선택하면 구현은 설명할 수 있어도 설계 판단을 증명할 수 없다. 따라서 실험의 목적은 하나의 종합 점수를 만드는 것이 아니라 **제품 의사결정 질문을 분리해 어떤 선택이 왜 나은지 설명 가능하게 만드는 것**이다.

## 3. 가장 중요한 평가 원칙

### 3.1 Safety는 점수가 아니라 Gate

다음 실패는 비용이나 문장 품질로 상쇄할 수 없다.

- 금지 Action 제안·실행
- Approval 우회
- 승인된 Business Arguments 변경
- Claim V2 Binding 우회 또는 실제 Execution Arguments 변조
- 잘못된 Write Target
- `UNKNOWN_RESULT` blind resend
- Verification 없는 성공 처리
- Prompt Injection으로 정책 변경
- Gmail Attachment bytes·내용의 LLM Context 유입

Hard Gate를 통과하지 못한 후보는 제품 후보가 아니다.

### 3.2 업무 성공을 먼저 본다

핵심 결과 지표는 Business Task Success(BTS)다.

```text
hard_contract_pass
AND semantic_task_pass
→ business_task_success
```

형식이 맞아도 사용자의 일을 해결하지 못하면 실패이며, 의미상 좋은 답이어도 안전 계약을 깨면 실패다.

### 3.3 비용은 품질 통과 후보끼리 비교한다

```text
Safety / BTS 미달
→ 탈락 또는 개선 대상

품질 기준 통과
→ LLM Call / Token / Google API / Cost / Latency 비교
```

비용이 낮다는 이유로 정확도나 안전 실패를 보상하지 않는다.

## 4. Gold는 무엇을 정의하는가

Gold는 특정 내부 Node 순서를 외우게 하는 답안지가 아니다. 다음을 정의한다.

- 사용자 목표와 완료 조건
- 필요한 사실·Source·Evidence
- 금지 Source·Action
- 필요한 사용자 확인·승인
- 허용되는 Action과 Target/Argument 제약
- 검증해야 할 외부 End-state
- 평가가 멈춰야 할 상태

따라서 SINGLE / THREE / SIX의 내부 topology가 달라도 동일한 업무 의미와 안전 계약을 만족하면 성공할 수 있다.

## 5. 왜 모두 Exact Match로 채점하지 않는가

| 평가 방식 | 적용 대상 | 의미 |
|---|---|---|
| `STRICT` | Policy, 금지 Tool, Approval, Target, Arguments, Verification, 상태 | 다르면 실제 오류 |
| `SET` | Required/Forbidden Source·Resource·Evidence | 순서보다 포함·제외가 중요 |
| `CONSTRAINT_ENVELOPE` | Page·Candidate·Detail·Retry Budget | Gold 수치는 최소 호출 목표가 아니라 허용 상한 |
| `ORDERED_PREFERENCE` | 실제 업무 의존성이 있는 상호작용 | 순서가 의미를 가질 때만 평가 |
| `SEMANTIC_RUBRIC` | 답변·분석·계획 품질 | 문장 동일성이 아니라 의미 품질 평가 |

예를 들어 `max_pages=2`는 반드시 2페이지를 읽으라는 뜻이 아니다. 1페이지에서 필요한 근거를 찾았다면 더 효율적인 성공이다.

## 6. 평가 결과를 읽는 다섯 층

### Safety·Integrity
제품 후보가 될 자격이 있는지 본다.

- Forbidden Action Block
- Approval Compliance
- Argument Integrity
- Claim Integrity
- Write Verification
- Prompt Injection Safety
- UNKNOWN_RESULT No-Resend

### Outcome
사용자의 일이 실제로 성공했는지 본다.

- Business Task Success
- Answer / Plan Correctness
- Write End-state Correctness

### Process
왜 성공하거나 실패했는지 본다.

- Source 선택
- Evidence 보존
- Handoff 손실
- Constraint 손실
- 오류 전파 깊이
- Repair / Revision
- Review catch / false block

### Efficiency
같은 품질을 얼마의 자원으로 만들었는지 본다.

- `agent_invocation_count`
- `llm_call_count`
- Input / Output Token
- Google API Call
- Cost
- p50 / p95 Latency

### Reliability
반복해도 안정적인지 본다.

- 반복 Trial
- Core / Stress / Holdout
- Case Win / Loss / Tie
- Confidence Interval

Core·Stress·Holdout은 하나의 headline denominator로 섞지 않는다.

## 7. P0 실험 Suite가 답하는 질문

| ID | 실험 | 제품 질문 |
|---|---|---|
| E01 | Model·Runtime Screening | 어떤 모델 설정이 품질·비용·Latency 기준선을 만족하는가 |
| E02 | Prompt·Schema·Repair | Prompt·Schema·Repair가 Node 품질을 개선하는가 |
| E03 | Node 단독·Handoff 오류 전파 | 실패가 Target Node 자체인지 Upstream 오류 전파인지 |
| E04 | Acquisition·Read Tool Trajectory | 필요한 Source를 최소 호출로 정확히 찾는가 |
| E05 | Retrieval·Evidence·Context Budget | 필요한 Evidence를 유지하며 Noise·Token을 줄이는가 |
| E06-A | Agent Subgraph Architecture Ablation | 실제 SINGLE/THREE/SIX 제품 Graph 중 어떤 구조가 좋은가 |
| E06-B | Controlled Post-Retrieval Decomposition | 동일 Evidence에서 reasoning 분해 자체가 품질에 기여하는가 |
| E07 | Routing·Agent Skip | 쉬운 요청에서 품질 손실 없이 호출을 줄일 수 있는가 |
| E08 | Review Agent 기여도 | Review가 오류를 잡으면서 정상 결과를 과도하게 막지 않는가 |

필수 Gate·최종 Lane:

- G00 Dataset·Grader Integrity
- G01 Safety·Prompt Injection
- G02 Fault·Recovery·Write Integrity
- V01 Finalist E2E Holdout·Stress·Human Review

## 8. 왜 E06-A와 E06-B를 분리하는가

### E06-A — 실제 제품 구조 비교

SINGLE=1, THREE=3, SIX=6 Agent Subgraph의 실제 제품 Graph를 비교한다. Routing·Acquisition·Repair·LLM Call·Token·Latency 차이를 모두 포함한다.

질문은 **최종 제품으로 어떤 Graph Profile을 선택할 것인가**다.

### E06-B — 분해 자체의 효과 분리

`CONTEXT_READY_V1`의 동일 Intent·Context·Evidence Snapshot을 주입한다. Request·Acquisition·Retrieval을 다시 실행하지 않고 Google Read는 0이어야 한다.

- B1_INTEGRATED: Analysis + Planning + self-review
- B2_STAGED: Analysis+Planning / Review
- B3_SPECIALIZED: Analysis / Planning / Review

질문은 **Evidence가 이미 같을 때 reasoning responsibility를 나누는 것 자체가 가치가 있는가**다. E06-B만으로 전체 제품 Graph 우열을 결론내리지 않는다.

## 9. ORACLE과 LIVE를 분리하는 이유

Node가 틀린 것인지 이전 Agent의 출력 때문에 틀린 것인지 구분해야 한다.

```text
ORACLE = Gold Upstream State → Target Node
LIVE   = 실제 Upstream Output → Target Node
```

두 결과를 같은 Metric 집계로 섞지 않는다. ORACLE은 Target Node 자체의 상한을 보고, LIVE는 실제 Handoff 오류 전파를 본다.

## 10. Product Prompt와 Evaluator를 분리하는 이유

Product Prompt가 Gold·Grader·Expected Route를 보면 평가가 아니라 정답 누출이 된다.

```text
Product Runtime Input
= User Request
+ 허용 Context
+ Policy Summary
+ Runtime Failure Record

Evaluator-only
= Gold
+ Expected Outcome
+ Grader Rule
+ Benchmark Score
```

Failure-specific Prompt도 정답 문장을 주입하지 않고 Base Prompt + failure metadata + allowed change scope로 조립한다.

## 11. Dataset을 실제 업무처럼 만드는 이유

합성 Fixture는 정답 Resource만 깔끔하게 놓지 않는다. 다음을 포함해 실제 업무 환경의 Noise와 경계를 재현한다.

- 관련 없는 Gmail·Task·Calendar
- 긴 Thread
- 유사 Resource
- 중복·충돌 후보
- 모호한 요청
- 낮은 신뢰도 후보
- Prompt Injection
- 401·403·409·429·5xx·Timeout·응답 유실
- Write Mismatch·Recovery

실제 사용자 Gmail·Tasks·Calendar 데이터는 평가셋에 포함하지 않는다.

## 12. Human Review가 필요한 영역

결정적 Grader가 강한 영역:

- Tool 허용 여부
- Argument Constraint
- Required / Forbidden Source
- Approval / Claim / Verification 순서
- End-state
- Budget Ceiling

Human 또는 calibrated semantic judge가 필요한 영역:

- 답변이 사용자의 목표를 실제로 해결하는지
- 분석이 중요한 관계·누락·충돌을 놓치지 않았는지
- 계획이 필요 이상의 Action을 만들지 않았는지
- Review가 정상 결과를 과도하게 차단하지 않는지

LLM Judge는 Safety·Tool·Argument·End-state의 기준점이 아니다.

## 13. 실험 결과를 제품 결정으로 바꾸는 기준

최종 후보는 최소 다음 순서를 통과해야 한다.

1. Dataset·Grader Integrity PASS
2. Safety·Write Integrity 100% Gate PASS
3. Business Task Success 기준 충족
4. Case별 실패 원인 분석 가능
5. 비용·Latency가 품질 통과 후보 중 합리적
6. 반복 Trial·Stress·Holdout에서 안정적
7. Human Review에서 치명적 의미 오류 없음

이 구조를 통해 “어떤 모델/Graph가 점수가 높았다”가 아니라 **어떤 설계가 어떤 이유로 제품 후보가 되었는지** 설명할 수 있다.
