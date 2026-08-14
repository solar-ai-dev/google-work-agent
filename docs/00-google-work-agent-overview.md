# Google Work Agent — Overview

Google Work Agent는 Connector 확장 가능한 Work Agent Core 위에 Google Workspace를 P0 첫 Connector로 제공하는 Windows 로컬 업무 Agent다.

```text
사용자 요청
→ Request Understanding
→ Tool Route semantic candidate
→ Registry + PolicyPreconditionResolver
→ Retrieval/RAG
→ effective analysis가 필요한 경우 Work Analysis
→ fixed OUT Route Planning
→ Review / Domain / Approval
→ Claim → MCP Write → Verification
```

## PHASE 7.5 현재 상태

- CanonicalCaseV7 / Base-92 유지.
- Dataset `rebuild-v1.17-r8.6-phase7.5-contract-correction`.
- Projection `projection-v1.1-r8.6-phase7.5`.
- `PrePolicyToolRouteGoldV1` 92건 추가.
- Prompt 0.9.0 내용은 변경하지 않았다.
- 실제 Ollama/qwen 실행 및 Holdout tuning은 아직 없다.
- 다음은 Runner 적용 후 CORE/DEV 실제 Local SLLM pilot이다.

## Canonical 문서 버전

PRD 2.10 / Functional 2.15 / Policy 2.11 / UI 2.11 / Architecture 3.6 / Domain 1.19 / Retrieval 2.12 / Workflow 7.15 / Interface 2.20 / Sequence 3.14 / Security 2.10 / Infrastructure 2.9 / Observability 2.19 / Test 3.32 / Evaluation 3.20 / Operations 2.17 / Prompt Contract 1.21.
