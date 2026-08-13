# 00-B. 평가·실험 전략과 선택 이유

## 목표
모델·Prompt·Tool Route·Retrieval·Agent 분해 수를 감으로 고르지 않고 동일 Canonical Case와 Fixture에서 비교한다.

## 평가 축
- Safety·Integrity: 100% Hard Gate
- Outcome: Business Task Success
- Process: Evidence/Handoff/오류 전파
- Efficiency: LLM Call/Token/MCP Tool Call/MCP 내부 Google Provider API Call/Cost/Latency
- Reliability: 반복 Trial/Holdout/Stress

Google 접근 비용은 `mcp_tool_call_count`/`mcp_read_tool_call_count`와 MCP Server 내부 `google_provider_api_call_count`를 분리해 측정한다. Core의 Provider API 직접 호출은 비교 후보가 아니라 계약 위반이다.

## 핵심 실험
E01 Model/Runtime, E02 Prompt·Schema·Repair, E03 Node/Handoff, E04 Tool Route·Read Trajectory, E05 Retrieval·Evidence·Context Budget, E06 Agent decomposition, E07 Routing/Skip, E08 Review 기여도를 분리한다.

## Dataset 기준
기존 결과 재현 Artifact와 새 Release Graph Gold를 구분한다. 새 Graph 평가 전 Dataset Rebase Gate를 거치며 Tool Route V2, Policy Precondition READ, Scope Confirmation, Duplicate/Conflict Override Receipt trajectory를 Gold에 반영한다.
