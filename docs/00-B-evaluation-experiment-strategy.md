# 00-B. 평가·실험 전략과 선택 이유

> 설명 문서다. 실험 권위 계약은 13, Prompt/Failure는 15, 제품 회귀는 12가 소유한다.

## 1. 평가 순서

```text
Dataset·Grader Integrity
→ Safety / Write Integrity Hard Gate
→ Business Task Success
→ Process 원인 분석
→ Efficiency 비교
→ Reliability / Holdout / Stress
→ Product Decision
```

## 2. 핵심 원칙

- Safety는 평균 점수가 아니라 **100% Gate**다.
- 1차 Outcome은 Business Task Success(BTS)다.
- 비용·지연은 품질을 통과한 후보끼리 비교한다.
- Gold는 내부 Graph topology가 아니라 사용자 목표·완료조건·필요 Evidence·금지 Action·검증 결과를 정의한다.
- STRICT/SET/CONSTRAINT_ENVELOPE/ORDERED_PREFERENCE/SEMANTIC_RUBRIC을 구분한다.
- Agent invocation과 LLM call을 별도 계수한다.
- Connector별 MCP Tool call과 Provider API call도 별도 계수한다.

## 3. P0 실험 질문

- E01 Model·Runtime
- E02 Prompt·Schema·Repair
- E03 Node·Handoff
- E04 Tool Route·Retrieval
- E05 Retrieval·Context
- E06-A Native 1/3/6 Architecture
- E06-B Controlled Post-Retrieval Decomposition
- E07 Routing·Skip
- E08 Review

Safety/Integrity Gate를 통과하지 못한 후보는 비용이 낮아도 Release 후보가 아니다.
