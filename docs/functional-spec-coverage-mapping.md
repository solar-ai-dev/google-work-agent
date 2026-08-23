# Functional Specification Coverage Mapping

이 문서는 설계 권위를 새로 정의하지 않는 파생 추적 보고서다. 기능 의미는 `docs/design/00-PROJECT-SOURCE-GUIDE.md`가 지정한 Project Source가 소유하며, 저장소 위치·이름은 `16-repository-architecture-source.md`가 소유한다.

## 판정 기준

- `IMPLEMENTED`: 문서 계약, canonical owner, runtime wiring, 회귀 테스트가 존재한다.
- `PARTIAL`: 일부 경로만 존재하거나 문서가 요구하는 활성화 gate가 남았다.
- `MISSING`: 문서 기능에 대응하는 구현 owner가 없다.
- `WRONG_IMPLEMENTATION`: 동작은 있으나 책임·권한·의존 방향이 canonical 계약과 다르다.
- P1에서 API를 제공하지 않는다고 명시한 항목은 그 부재 자체가 P0의 구현 계약이다.

## 기능별 코드 소유권 매핑

표의 `Owner`는 `Directory / File`, `Symbol`은 `Class / Function`, `Test`는 대표 자동 회귀다. `adapters/`, `api/`, `application/`, `domain/`, `launcher/`, `ports/`로 시작하는 backend 경로는 `src/google_work_agent/` 기준 상대 경로다.

### 설정·Runtime

| ID | Capability | 판정 | Owner | Symbol | Test |
|---|---|---|---|---|---|
| FN-001 | 최초 실행 온보딩 | IMPLEMENTED | `frontend/src/features/onboarding/OnboardingChecklist.tsx`; `adapters/runtime/settings.py` | `OnboardingChecklist`; `SettingsService.patch()` | `frontend/src/app/App.test.tsx`; `tests/unit/adapters/runtime/test_app_settings_store.py` |
| FN-002 | Google 계정 연결 | IMPLEMENTED | `application/use_cases/connector_connection/start_oauth.py`; `adapters/mcp/oauth.py` | `StartOAuthHandler.__call__()`; `MCPGoogleOAuthCredentialProvider.start_oauth()` | `tests/component/api/test_google_connection_api.py`; `tests/contract/oauth/test_mcp_oauth.py` |
| FN-003 | Google 계정 연결 해제 | IMPLEMENTED | `application/use_cases/connector_connection/disconnect_connector.py`; `api/routes/google_connections.py` | `DisconnectConnectorHandler.__call__()`; `disconnect_google()` | `tests/component/api/test_google_connection_api.py` |
| FN-004 | LLM Runtime 진단 | IMPLEMENTED | `adapters/llm/status.py`; `api/routes/llm_connections.py` | `LLMRuntimeStatusService.get_summary()`; `test_llm_connection()` | `tests/component/api/test_llm_runtime_api.py`; `tests/unit/llm/test_runtime_service.py` |
| FN-005 | LLM 모드 선택 | IMPLEMENTED | `adapters/runtime/settings.py`; `adapters/llm/router.py` | `SettingsService.patch()`; `LLMRuntimeRouter.invoke()` | `tests/unit/adapters/runtime/test_app_settings_store.py`; `tests/unit/llm/test_router.py` |
| FN-006 | 배포 프로필 선택 | IMPLEMENTED | `adapters/runtime/build_manifest.py` | `BuildProfile`; `validate_build_manifest()` | `tests/component/api/test_runtime_infrastructure_api.py` |
| FN-007 | OAuth 배포 환경 | IMPLEMENTED | `ports/google_oauth.py`; `adapters/connectors/google/mcp/oauth_settings.py` | `OAuthEnvironment`; `OAuthSettings` | `tests/unit/mcp/test_settings.py`; `tests/contract/oauth/test_mcp_oauth.py` |
| FN-008 | Local Agent Service 시작 | IMPLEMENTED | `launcher/dev.py`; `adapters/runtime/launcher.py` | `build_container()`; `LocalServiceLauncher.launch()` | `tests/integration/launcher/test_dev_service.py` |
| FN-009 | Frontend·API 세션/버전 | IMPLEMENTED | `api/routes/sessions.py`; `api/dependencies/contract_version.py` | `bootstrap_session()`; `enforce_supported_api_contract_version()` | `tests/integration/api/test_local_security.py`; `frontend/src/api/index.test.ts` |

### 요청·대화·이벤트

| ID | Capability | 판정 | Owner | Symbol | Test |
|---|---|---|---|---|---|
| FN-010 | 자연어 요청 입력 | IMPLEMENTED | `application/use_cases/run/start_run.py`; `api/routes/runs.py` | `StartRunHandler.__call__()`; `start_run()` | `tests/component/api/test_product_runtime_e2e.py` |
| FN-011 | 요청 범위 제한 | IMPLEMENTED | `application/agents/request_understanding/validate_intent.py` | `validate_intent()` | `tests/unit/application/workflows/test_request_understanding.py` |
| FN-012 | 실행 취소 | IMPLEMENTED | `application/use_cases/run/request_cancel.py` | `RequestCancelHandler.__call__()` | `tests/integration/persistence/test_write_cancellation.py` |
| FN-013 | Run 재개 | IMPLEMENTED | `application/use_cases/run/resume_run.py` | `ResumeRunHandler.__call__()` | `tests/unit/application/use_cases/run/test_resume_run.py` |
| FN-014 | 사이드바 목록 조회 | IMPLEMENTED | `application/use_cases/resource_ref/list_resources.py`; `frontend/src/features/*` | `ListResourcesHandler.__call__()`; `useGmail/useTasks/useCalendar` | `tests/unit/application/use_cases/resource_ref/test_resource_ref_handlers.py`; `frontend/src/app/App.test.tsx` |
| FN-015 | Frontend 페이지 메모리 캐시 | IMPLEMENTED | `frontend/src/features/gmail/useGmail.ts`; `frontend/src/features/tasks/useTasks.ts` | source hooks의 page cache | `frontend/src/app/App.test.tsx` |
| FN-016 | 사용자 선택형 요청 | IMPLEMENTED | `ports/workflow_runtime.py`; `application/run_contracts.py` | `SelectedResourceRef`; `StartRunCommand.selected_resources` | `tests/component/api/test_product_runtime_e2e.py` |
| FN-017 | Agent 검색형 요청 | IMPLEMENTED | `application/orchestration/supervisor.py` | `route_supervisor()` | `tests/unit/application/workflows/test_supervisor.py` |
| FN-018 | Run Event Stream 구독·복구 | IMPLEMENTED | `api/routes/events.py`; `application/use_cases/run/get_event_replay.py` | `stream_events()`; `GetEventReplayHandler.__call__()` | `tests/unit/application/use_cases/run/test_get_event_replay.py` |
| FN-019 | Command Receipt | IMPLEMENTED | `application/run_command_receipts.py`; `ports/persistence/command_receipt_repository.py` | receipt resolve/finish functions | `tests/unit/application/test_start_run_receipt_recovery.py`; `tests/integration/persistence/test_write_actions.py` |

### Retrieval

| ID | Capability | 판정 | Owner | Symbol | Test |
|---|---|---|---|---|---|
| FN-020 | Source 선택 | IMPLEMENTED | `application/agents/tool_routing/determine_io_resources.py` | `determine_io_resources()` | `tests/unit/application/agents/tool_routing/test_determine_io_resources.py` |
| FN-021 | Gmail 검색·조회 | IMPLEMENTED | `application/use_cases/resource_ref/list_resources.py`; `adapters/connectors/google/gmail/**` | `ListResourcesHandler.__call__()` | `tests/unit/mcp/test_workspace_read_tools.py` |
| FN-021A | Gmail 첨부 조회·다운로드 | IMPLEMENTED | `application/use_cases/attachment/fetch_attachment.py`; `api/routes/attachments.py`; `frontend/src/features/workspace/ResourceDetail.tsx` | `FetchAttachmentHandler.__call__()`; `download_gmail_attachment()` | `tests/component/api/test_attachment_api.py`; `frontend/src/app/App.test.tsx` |
| FN-022 | Tasks 검색·조회 | IMPLEMENTED | `application/use_cases/resource_ref/list_resources.py`; `adapters/connectors/google/tasks/**` | `ListResourcesHandler.__call__()` | `tests/unit/mcp/test_workspace_read_tools.py` |
| FN-023 | Calendar 조회·FreeBusy | IMPLEMENTED | `application/orchestration/retrieval_read_executor.py`; `adapters/connectors/google/calendar/**` | `RetrievalReadExecutor.execute()` | `tests/integration/retrieval/test_calendar_freebusy_chain.py` |
| FN-024 | Context 정규화 | IMPLEMENTED | `application/agents/retrieval/normalize_segments.py` | `normalize_segments()` | `tests/unit/application/agents/retrieval/test_retrieval_operations.py` |
| FN-025 | Chunking | IMPLEMENTED | `application/agents/retrieval/normalize_segments.py` | `_chunk_text()` | `tests/integration/retrieval/test_gmail_body_chunk_evidence_chain.py` |
| FN-026 | 재검색 | IMPLEMENTED | `application/agents/retrieval/assess_sufficiency.py`; `application/orchestration/retrieval_rounds.py` | `assess_sufficiency()`; `RetrievalRoundController` | `tests/integration/retrieval/test_retrieval_v2_trajectories.py` |
| FN-027 | 사용자 확인 질문 | IMPLEMENTED | `domain/confirmation.py`; `application/use_cases/run/resume_run.py` | `ConfirmationRequestV1`; `ResumeRunHandler.__call__()` | `tests/integration/langgraph/test_retrieval_confirmation.py` |
| FN-028 | Embedding·Reranking 실험 | IMPLEMENTED | `application/agents/retrieval/rag_retrieve_rerank.py`; `scripts/experiments/run_retrieval_baseline.py` | `rag_retrieve_rerank()`; experiment entry point | `tests/unit/application/agents/retrieval/test_retrieval_operations.py` |

### 분석·계획

| ID | Capability | 판정 | Owner | Symbol | Test |
|---|---|---|---|---|---|
| FN-030 | Resource 관계 연결 | IMPLEMENTED | `application/agents/work_analysis/resolve_entity_relations.py`; `resolve_temporal_dependencies.py` | `resolve_entity_relations()`; `resolve_temporal_dependencies()` | `tests/unit/application/agents/work_analysis/test_atomic_operations.py` |
| FN-031 | Task 중복 검사 | IMPLEMENTED | `application/task_duplicates.py` | `TaskDuplicateValidator.fresh_risk()` | `tests/integration/persistence/test_write_policies.py` |
| FN-032 | Calendar 충돌 검사 | IMPLEMENTED | `application/calendar_conflicts.py` | `CalendarConflictValidator.fresh_risk()` | `tests/integration/retrieval/test_calendar_freebusy_chain.py` |
| FN-033 | 업무 가능성 판단 | IMPLEMENTED | `application/feasibility.py`; `application/agents/work_analysis/assess_operational_risks.py` | `FeasibilityValidator.fresh_risk()`; `assess_operational_risks()` | `tests/unit/application/workflows/test_work_analysis.py` |
| FN-040 | Action Plan 생성 | IMPLEMENTED | `application/agents/planning/assemble_plan.py` | `assemble_plan()` | `tests/unit/application/agents/planning/test_planning_deterministic_operations.py` |
| FN-041 | Action DAG 생성 | IMPLEMENTED | `application/agents/planning/build_dependencies.py` | `build_dependencies()` | `tests/unit/application/agents/planning/test_planning_deterministic_operations.py` |
| FN-042 | Gmail Draft 제안 | IMPLEMENTED | `application/orchestration/planning_argument_writer.py` | `PlanningArgumentWriter.write()` | `tests/unit/application/test_planning_argument_writer.py` |
| FN-042A | Gmail Draft·Send 첨부 | IMPLEMENTED | `adapters/runtime/attachment_staging.py`; `application/write_claim.py`; `frontend/src/features/conversation/useConversation.ts` | `LocalAttachmentStaging.verify_descriptor()`; `ClaimWriteActionService._verify_attachments_before_transaction()`; `handleAttachFiles()` | `tests/unit/mcp/test_attachment_tools.py`; `tests/integration/persistence/test_write_actions.py`; `frontend/src/app/App.test.tsx` |
| FN-043 | Task 제안 | IMPLEMENTED | `application/orchestration/planning_arguments.py` | `DefaultContainerResolver.resolve()` | `tests/unit/application/workflows/test_canonical_planning_arguments.py` |
| FN-044 | 작업 Event 제안 | IMPLEMENTED | `application/orchestration/planning_argument_writer.py` | `PlanningArgumentWriter.write()` | `tests/unit/application/test_planning_argument_writer.py` |

### 승인·실행·검증·복구

| ID | Capability | 판정 | Owner | Symbol | Test |
|---|---|---|---|---|---|
| FN-050 | Context Preview | IMPLEMENTED | `application/use_cases/run/get_run_snapshot.py`; `frontend/src/features/conversation/ConversationView.tsx` | `GetRunSnapshotHandler.__call__()`; approval card projection | `frontend/src/app/App.test.tsx` |
| FN-051 | Action 승인 | IMPLEMENTED | `application/use_cases/action/approve_action.py` | `ApproveActionHandler.__call__()` | `tests/unit/application/use_cases/approval/test_approve_action_source_snapshot.py` |
| FN-052 | Action 수정 | IMPLEMENTED | `application/use_cases/action/modify_action.py`; `frontend/src/features/conversation/ConversationView.tsx` | `ModifyActionHandler.__call__()`; typed title/subject/attachment patch | `tests/integration/persistence/test_action_modify_vertical_slice.py`; `frontend/src/app/App.test.tsx` |
| FN-053 | Action 거절 | IMPLEMENTED | `application/use_cases/action/reject_action.py` | `RejectActionHandler.__call__()` | `tests/integration/persistence/test_action_reject_vertical_slice.py` |
| FN-054 | 승인 Token·Claim 발급 | IMPLEMENTED | `application/write_claim.py`; `application/write_execution_integrity.py` | `ClaimWriteActionService.__call__()`; `issue_claim_token()` | `tests/unit/domain/action/test_action_approval_claim_transitions.py` |
| FN-060 | MCP Tool 실행 | IMPLEMENTED | `adapters/connectors/google_workspace_execution.py` | `GoogleWorkspaceExecutionBackend.execute_write()` | `tests/integration/test_write_lifecycle_closure.py` |
| FN-061 | Idempotency | IMPLEMENTED | `application/write_persistence.py`; command receipt repositories | `resolve_existing_action_receipt()` | `tests/unit/application/use_cases/action/test_action_handler_idempotency.py` |
| FN-062 | 부분 실행 | IMPLEMENTED | `application/write_run_completion.py` | `CompleteWriteRunService.__call__()` | `tests/integration/persistence/test_write_cancellation.py` |
| FN-070 | 실행 결과 검증 | IMPLEMENTED | `application/use_cases/verification/verify_action.py`; `application/write_verification.py` | `VerifyActionHandler.__call__()`; `VerifyWriteActionService.__call__()` | `tests/unit/application/use_cases/test_c3_execution_recovery_verification.py` |
| FN-071 | 정상화 비교 | IMPLEMENTED | `application/use_cases/verification/normalize_snapshot.py` | `normalize_snapshot()` | `tests/unit/application/test_write_verification_projection.py` |
| FN-072 | Mismatch Recovery | IMPLEMENTED | `application/use_cases/recovery/resolve_mismatch_recovery.py` | `ResolveMismatchRecoveryHandler.__call__()` | `tests/integration/test_corrective_recovery_reachability.py` |
| FN-073 | OAuth 재인증 후 재개 | IMPLEMENTED | `application/use_cases/run/require_reauth.py`; `resume_run.py` | `RequireReauthHandler`; `ResumeRunHandler` | `tests/unit/application/test_preflight_reauth.py` |
| FN-074 | Google OAuth 연결 Coordinator | IMPLEMENTED | `application/use_cases/connector_connection/**`; `application/coordinator.py` | connector connection handlers; `LocalRunCoordinator` | `tests/unit/application/use_cases/connector_connection/test_get_connection_handler.py` |
| FN-075 | 실행 Claim 증명 | IMPLEMENTED | `domain/claim_contract.py`; `application/write_execution_integrity.py` | `ClaimContextV2`; `validate_claim_token()` | `tests/unit/application/test_complete_write_run_guard.py` |
| FN-076 | 대화 이름 변경 미제공(P1) | IMPLEMENTED | `api/routes/conversations.py` | rename route 없음 | `tests/architecture/test_run_conversation_event_api_authority.py` |
| FN-077 | 대화 삭제 미제공(P1) | IMPLEMENTED | `api/routes/conversations.py` | delete route 없음 | `tests/architecture/test_run_conversation_event_api_authority.py` |

### 관측성·실험·Multi-Agent

| ID | Capability | 판정 | Owner | Symbol | Test |
|---|---|---|---|---|---|
| FN-080 | Run Trace | IMPLEMENTED | `ports/observability_events.py`; `adapters/persistence/sqlite/repositories/trace_repository.py` | trace event contracts; `SqliteTraceRepository.add()` | `tests/unit/test_observability.py` |
| FN-081 | Audit Log | IMPLEMENTED | `adapters/persistence/sqlite/repositories/audit_repository.py` | `SqliteAuditRepository.add()` | `tests/integration/persistence/test_secret_boundary.py` |
| FN-082 | 사용자 진단 화면 | IMPLEMENTED | `frontend/src/features/settings/SettingsDrawer.tsx`; `adapters/mcp/stdio_transport.py` | `SettingsDrawer`; `MCPRuntimeStatusProvider.get_summary()` | `tests/unit/adapters/mcp/test_runtime_status_provider.py`; `frontend/src/app/App.test.tsx` |
| FN-090 | Experiment Runner | IMPLEMENTED | `scripts/experiments/run_*.py` | 각 experiment entry point | `tests/evaluation/**` |
| FN-091 | 평가 리포트 | IMPLEMENTED | `scripts/experiments/run_workflow_ablation.py`; `run_model_screening.py` | report emitters | `tests/evaluation/**` |
| FN-092 | 제품 설정 채택 | IMPLEMENTED | `adapters/runtime/build_manifest.py`; `experiments/candidates/**` | signed build/model manifest gate | `tests/component/api/test_runtime_infrastructure_api.py` |
| FN-093 | sLLM 실험 분리 | IMPLEMENTED | `scripts/experiments/**`; production→evaluation architecture gate | separate process entry points | `tests/architecture/test_repository_architecture.py` |
| FN-100 | Supervisor Routing | IMPLEMENTED | `application/orchestration/supervisor.py` | `route_supervisor()` | `tests/unit/application/workflows/test_supervisor.py` |
| FN-101 | 요청 이해 Agent | IMPLEMENTED | `adapters/langgraph/subgraphs/request_understanding/graph.py` | `RequestUnderstandingSubgraph.build()` | `tests/unit/adapters/langgraph/test_ru_tr_canonical_cutover.py` |
| FN-102 | Tool Route Agent | IMPLEMENTED | `adapters/langgraph/subgraphs/tool_routing/graph.py` | `ToolRoutingSubgraph.build()` | `tests/integration/langgraph/test_tool_route_confirmation.py` |
| FN-102A | Policy Precondition·Scope Confirmation | IMPLEMENTED | `application/agents/tool_routing/finalize_route.py`; `domain/confirmation.py` | `finalize_route()`; confirmation contract | `tests/integration/langgraph/test_tool_route_confirmation.py` |
| FN-103 | Retrieval Agent | IMPLEMENTED | `adapters/langgraph/subgraphs/retrieval/graph.py` | `RetrievalSubgraph.build()` | `tests/integration/retrieval/test_retrieval_v2_trajectories.py` |
| FN-104 | 업무 분석 Agent | IMPLEMENTED | `adapters/langgraph/subgraphs/work_analysis/graph.py` | `WorkAnalysisSubgraph.build()` | `tests/integration/langgraph/test_work_analysis_confirmation.py` |
| FN-105 | Planning Agent | IMPLEMENTED | `adapters/langgraph/subgraphs/planning/graph.py` | `PlanningSubgraph.build()` | `tests/integration/langgraph/test_canonical_planning_migration.py` |
| FN-106 | 계획 검토 Agent | IMPLEMENTED | `adapters/langgraph/subgraphs/review/runtime_active_graph.py` | `RuntimeActiveReviewSubgraph` | `tests/unit/adapters/langgraph/test_planning_review_execution.py` |
| FN-107 | Typed Handoff·Checkpoint | IMPLEMENTED | `application/orchestration/handoff_contracts.py`; `adapters/langgraph/graph_state.py` | versioned TypedDicts; `initial_graph_state()` | `tests/integration/retrieval/test_retrieval_checkpoint_boundary.py` |
| FN-108 | 응답 조립 | IMPLEMENTED | `application/orchestration/assemble_planning_answer.py`; `adapters/langgraph/response_workflow.py` | `assemble_planning_answer()` | `tests/unit/adapters/langgraph/test_response_synthesis_runtime.py` |
| FN-109 | Retrieval Subgraph 실행 | IMPLEMENTED | `adapters/langgraph/subgraphs/retrieval/graph.py` | `RetrievalSubgraph.invoke()` | `tests/integration/langgraph/test_retrieval_detail_fetch.py` |
| FN-110 | Answer-only Run 완료 | IMPLEMENTED | `application/use_cases/run/complete_answer_only_run.py` | `CompleteAnswerOnlyRunHandler.__call__()` | `tests/unit/domain/run/transitions/test_complete_answer_only_run.py` |
| FN-111 | READ-only Plan | IMPLEMENTED | `application/read_plan.py`; `application/read_execution.py` | `SaveReadOnlyPlanService`; `ExecuteReadActionService` | `tests/integration/persistence/test_read_only.py` |
| FN-112 | READ 실패 | IMPLEMENTED | `application/read_execution.py` | `FailReadActionService.__call__()` | `tests/integration/persistence/test_read_only.py` |
| FN-113 | Write 재시도 준비 | IMPLEMENTED | `application/use_cases/action/prepare_write_retry.py` | `PrepareWriteRetryHandler.__call__()` | `tests/unit/application/use_cases/test_c3_execution_recovery_verification.py` |
| FN-114 | 결정적 Supervisor | IMPLEMENTED | `application/orchestration/supervisor.py` | `route_supervisor()` | `tests/unit/application/workflows/test_supervisor.py` |
| FN-115 | Agent Subgraph 실행 계약 | IMPLEMENTED | `adapters/langgraph/agent_kernel.py`; 각 owner-local graph | budget/trace/schema kernel functions | `tests/unit/adapters/langgraph/test_agent_kernel_budget.py`; `tests/integration/langgraph/test_runtime_state_boundaries.py` |

## Canonical atomic operation mapping

`16 Repository Architecture v1.4`의 closed list는 40개다. 각 항목은 같은 이름의 `application/agents/<agent>/<operation>.py` 함수가 의미를 소유하고, `adapters/langgraph/subgraphs/<agent>/nodes/<operation>_node.py`가 얇은 graph adapter를 소유한다.

| Agent | Operation modules | 대표 Test | 판정 |
|---|---|---|---|
| Request Understanding | `identify_goal`, `detect_ambiguity`, `finalize_intent`, `validate_intent` | `tests/unit/application/workflows/test_request_understanding.py` | IMPLEMENTED |
| Tool Routing | `determine_io_resources`, `bind_registry_candidates`, `select_tool_if_needed`, `finalize_route`, `validate_route` | `tests/unit/application/agents/tool_routing/**` | IMPLEMENTED |
| Retrieval | `plan_query`, `build_query`, `execute_read`, `normalize_segments`, `rag_retrieve_rerank`, `select_evidence`, `assess_sufficiency`, `finalize_retrieval` | `tests/unit/application/agents/retrieval/test_retrieval_operations.py` | IMPLEMENTED |
| Work Analysis | `extract_work_facts`, `resolve_entity_relations`, `resolve_temporal_dependencies`, `detect_duplicate_conflict_candidates`, `validate_relations`, `assess_information_gaps`, `assess_operational_risks`, `assemble_work_analysis`, `validate_work_analysis` | `tests/unit/application/agents/work_analysis/**` | IMPLEMENTED |
| Planning | `choose_answer_or_action_from_route`, `outline_answer`, `compose_answer`, `draft_action_objective_per_output_route`, `compose_arguments_per_output_route`, `build_dependencies`, `assemble_plan`, `validate_plan` | `tests/unit/application/agents/planning/**` | IMPLEMENTED |
| Review | `inspect_goal_and_evidence`, `inspect_action_scope_and_route`, `inspect_constraints_and_policy_summary`, `aggregate_review_findings`, `validate_review`, `recheck_affected_dimensions` | `tests/unit/application/agents/review/**`; `tests/unit/adapters/langgraph/test_review_dimension_recheck.py` | IMPLEMENTED |

## 문서군 교차 추적

| Source | 문서 단위 | 코드/테스트 매핑 |
|---|---|---|
| PRD | UC-01~UC-05 | FN-010~075의 요청→Retrieval→분석→계획→승인→실행→검증 행 |
| PRD | FR-001~008 | FN-001~009; launcher/security/API component tests |
| PRD | FR-010~016 | FN-004~007; LLM/runtime tests |
| PRD | FR-020~026 | FN-010, 020~028; retrieval integration tests |
| PRD | FR-030~034 | FN-030~044; work-analysis/planning tests |
| PRD | FR-040~044 | FN-050~054; approval/modify/domain transition tests |
| PRD | FR-050~059 | FN-060~075; write safety/recovery/SSE/receipt tests |
| PRD | FR-060~065 | FN-080~093; observability/evaluation/architecture gates |
| PRD | NFR-001~028 | local-only security, secret boundary, latency/budget, DB invariant, recovery, architecture suites |
| Architecture | layer/port/composition rules | `tests/architecture/**` |
| Workflow | deterministic Supervisor, six subgraphs, Typed Handoff | `tests/integration/langgraph/**` |
| Sequence | Start/Confirm/Approve/Claim/Execute/Verify/Recover 순서 | `tests/component/api/test_product_runtime_e2e.py`; `tests/integration/test_write_lifecycle_closure.py` |
| Domain Contract | Aggregate·상태 전이·Command Receipt·Migration 0001~0008 | `tests/unit/domain/**`; `tests/integration/persistence/**` |
| Test Design | TST-DB/API/SEC/MCP/WF/E2E/EVAL-101~108 | architecture/component/contract/evaluation suites |
| Test Design | TST-AGT/RET/HANDOFF-201~226 | agent operation, LangGraph, retrieval suites |
| Test Design | TST-UI-201~213 | `frontend/src/app/App.test.tsx` |

## 폐쇄 결과와 남은 계약 상태

- P0/P1 Functional Definition 행: `IMPLEMENTED 79`, `PARTIAL 0`, `MISSING 0`, `WRONG_IMPLEMENTATION 0`.
- 구조·기능 구현과 별개로 Prompt `0.9.2-r8.6-sllm-decomposition`은 문서가 `DRAFT → DEV_VALIDATED → HOLDOUT_VALIDATED → SAFETY_VALIDATED → RUNTIME_ACTIVE`를 요구한다. 현재 code/manifest/node owner는 materialized됐지만 gate는 실행되지 않았으므로 runtime은 승인된 `0.9.1` 경로를 유지한다. 이는 제품 기능 누락이 아니라 의도된 candidate activation 상태다.
- OAuth 운영 Client/동의 화면과 실제 Google 계정에 대한 live 검증은 저장소 자동 테스트로 대체할 수 없는 배포 검증 항목이다.
