# 00-B. 평가·실험 전략과 선택 이유

> 이 문서는 평가 전략의 설명용 요약이다. 권위 계약은 13 Evaluation, 12 Test, 11 Observability, 15 Prompt/Failure 문서가 가진다.

## 1. 평가의 목적

제품 선택을 “그럴듯함”으로 결정하지 않고 동일 Case/Fixture/Policy/Tool Schema에서 반복 가능한 실험으로 비교한다.

```text
Dataset·Grader Integrity
→ Safety / Write Integrity Hard Gate
→ Business Task Success
→ Process 분석
→ Efficiency 비교
→ Reliability / Holdout / Stress
→ Product Decision
```

## 2. 안전은 점수가 아니라 Gate

다음 실패는 낮은 비용이나 좋은 문장 품질로 상쇄하지 않는다.

- 금지 Action
- Approval 우회
- 승인 Arguments 변경
- Claim 무결성 우회
- 잘못된 Write Target
- UNKNOWN_RESULT resend
- Verification 누락
- Prompt Injection에 의한 정책 변경

## 3. 업무 성공

```text
hard_contract_pass
AND semantic_task_pass
→ business_task_success
```

형식만 맞거나 문장만 좋아서는 성공이 아니다.

## 4. Gold의 역할

Gold는 특정 Graph 내부 Node 순서를 외우게 하지 않는다. 사용자 목표, 필요한 Evidence/Route, 금지 조건, 사용자 상호작용, Expected End-state를 정의한다.

Connector Route Gold에는 `connector_id + InputRoutePlan + OutputPlan`을 포함한다. P0 Fixture는 `google_workspace / Gmail|Tasks|Calendar` 합성 데이터다.

## 5. 평가 축

- **Safety·Integrity**: 후보 자격
- **Outcome**: BTS, Answer/Plan/Write 결과
- **Process**: Route, Retrieval, Evidence, Handoff, Repair/Revision
- **Efficiency**: Agent Invocation, LLM Call, Token, Connector MCP Tool Call, Provider API Call, Cost, Latency
- **Reliability**: Trial, Holdout, Stress

## 6. 주요 실험

| ID | 질문 |
|---|---|
| E01 | 어떤 Model/Runtime이 기준선을 만족하는가 |
| E02 | Prompt/Schema/Repair가 Node 품질을 개선하는가 |
| E03 | 실패가 Node 자체인지 Handoff 전파인지 |
| E04 | Connector/IN/OUT Route와 Read trajectory가 정확한가 |
| E05 | Evidence를 유지하며 Context/Token을 줄일 수 있는가 |
| E06-A | 실제 1/3/6 Graph 중 어떤 구조가 좋은가 |
| E06-B | 동일 Evidence에서 reasoning 분해 자체가 기여하는가 |
| E07 | 쉬운 요청에서 Agent skip이 안전한가 |
| E08 | Review가 실제 오류를 줄이는가 |

## 7. Connector 비용 측정

Connector별로:

```text
connector_id
mcp_tool_call_count
mcp_read_tool_call_count
provider_api_call_count
```

를 분리한다. `provider_api_call_count`는 Connector MCP Server 내부 Adapter의 호출량이며 Core direct Provider 호출을 허용한다는 의미가 아니다.

## 8. Dataset Rebase

구 Google-only Source 표현이나 구 Acquisition/Context Retriever trajectory는 새 Connector-aware Gold의 권위값으로 그대로 사용하지 않는다. 새 Gold는 현재 ToolRoutePlan/Connector Route/Retrieval 계약으로 Rebase Gate를 통과해야 한다.
