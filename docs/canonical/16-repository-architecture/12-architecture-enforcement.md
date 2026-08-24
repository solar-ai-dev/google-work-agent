# 12. Architecture Enforcement

**Normative detail of the current Repository Architecture Source.**

Architecture checks must be machine-enforceable where practical.

Required enforcement families:

- forbidden production filename patterns, including generic `runtime.py/service.py/manager.py/processor.py/engine.py/handler.py/helpers.py/utils.py/common.py/shared.py/misc.py/config.py` and broad multi-authority `errors.py` unless explicitly registered
- forbidden dependency edges/imports
- Provider SDK access outside connector MCP adapters
- multiple semantic-authority detection
- `_compat` zero on `main`
- production→evaluation import ban
- Evaluation repository root exact: current code/data/result/scoring artifacts live under top-level `evaluation/`; current top-level `experiments/` tree zero, with historical/imported artifacts isolated under `evaluation/compat/`
- Evaluation non-Python artifact closure: `canonical_cases_v7.jsonl`, current projection filenames, six Micro Dataset JSONL files, scoring contract, and 13 §18 result filenames match the 13/16 exact manifest
- static fixture grammar closure: checked-in provider/resource fixtures use `tests/fixtures/data/<provider>/<resource>/<scenario>.json` UTF-8 JSON; architecture validators do not require an enumerated concrete `<scenario>` closed set unless an owner source explicitly names one
- LangGraph node thin-adapter boundary
- routing operation-per-file: final production `routing/route_after_<stage>.py`, no catch-all `routing.py`
- Domain transition/guard operation-per-file; no broad multi-capability `commands.py`, `transitions.py`, or `guards.py`
- Agent semantic responsibility operation-per-file under `application/agents/<role>/`
- owner-local contract package rule; no global catch-all production `contracts/` package
- unit-test mirror checks for migrated capabilities
- direct concrete-adapter imports from Application
- barrel exports that hide concrete authority
- Current Workflow atomic responsibility ownership: heavy-Agent broad modules must not collapse distinct `facts / relations / gaps / risks`, `action objective / arguments`, or Review inspection dimensions into one production implementation file
- Local SLLM node implementation paths must map one semantic LLM responsibility to one owner-local operation file; deterministic aggregators/builders remain separate from LLM callers
- Domain Repository manifest exact coverage: every 04 persistence capability maps to one owner-specific Repository + SQLite adapter + test; generic Repository authority zero
- registry separation/uniqueness: exactly one `ConnectorRuntimeRegistry`, `SignedToolRegistry`, `NodeRegistry`, `ResumeTargetRegistry`, `PromptRegistry`, and Graph Profile Registry; no catch-all registry/service locator
- Prompt runtime exact-set closure: 15 current 21 `prompt_slot_id` set = runtime Product-LLM caller set = `prompt_manifest.json` = concrete `sources/<prompt_id>.md` = `prompt_runtime_input_contract_v1.json`; `prompt_id == prompt_slot_id`, duplicate/missing/extra/broad-predecessor Prompt source zero
- Prompt input-contract loader exact: `application/prompt_runtime/load_prompt_input_contract.py → load_prompt_input_contract()` is the only repository loader/validator for `PromptRuntimeInputContractV1`; alternate generic config loader authority zero
- exact 35 Agent Runtime Node adapter/projection/router manifest coverage; supporting deterministic operations must not create extra runtime nodes
- one production composition root: `api/composition.py → build_production_runtime()`; concrete binding outside it zero
- handoff reconciliation owner exact: `application/use_cases/run/redrive_workflow_handoffs.py → RedriveWorkflowHandoffsHandler`; same handler owns startup + live semantics with precedence CONSUMED active-continuation/domain fence → BLOCKED_BINDING Recovery → PENDING/DISPATCHED dispatch head → generic SAFE. `adapters/system/workflow_handoff_reconciliation_loop.py → WorkflowHandoffReconciliationLoop` may only drive that handler; direct loop/startup WEP/LangGraph orchestration zero
- WorkflowHandoff persisted projection exact: StageV1 vs persisted V1 separated; persisted row includes `run_sequence`, `version`, optional `WorkflowExecutionAdmissionV1`, submit-failure reason, applied checkpoint evidence, nullable no-control hash, `SUPERSEDED`; trigger lookup only through `get_by_trigger_command_id`. `GraphCheckpointEnvelopeV1` additionally carries `active_handoff_id/run_sequence` typed lineage until release boundary
- WorkflowHandoff ordering/transition surface exact: `get_dispatch_head`, `list_redriveable`, `list_blocked_binding`, pre-WEP `claim_execution_admission`, authority-aware non-ACCEPTED `release_execution_admission`, NORMAL CONSUMED settlement, CONSUMED recovery-admission settlement, `supersede_unconsumed_for_run`, SUPERSEDED settlement; raw SQL reset/reorder side-channel zero. Exact same-admission WEP replay is idempotent ACCEPTED. Release/settlement must compare persisted admission expected Run version with current Run.version; stale NORMAL admission is retired to SUPERSEDED rather than restored to PENDING/BLOCKED, and stale recovery admission is cleared while status remains CONSUMED. `CONSUMED_CONTINUATION_RECOVERY` bypasses dispatch-head membership only through `ScheduleRunExecutionHandler`, claims a persisted RESUME admission from the latest active-lineage checkpoint, and never mutates CONSUMED back to dispatch status
- operational artifact recovery exact: replay reservation `operation_ref` reaches Backup/Restore/Diagnostics/Attachment callables and their `reconcile_*`; Application raw filesystem reconciliation zero
- `StructuredInferencePort` production binding exactly one `StructuredInferenceRuntimeRouter`; direct leaf provider binding to Application/Agent zero
- external API LLM leaf grammar exact: `adapters/llm/<provider>/structured_inference.py → <Provider>StructuredInferenceAdapter`, `credential.py → <Provider>LlmCredentialAdapter`, `runtime_status.py → <Provider>LlmRuntimeStatusAdapter`; alternate live symbols/paths zero
- P0 local LLM leaf exact: `adapters/llm/ollama/structured_inference.py → OllamaStructuredInferenceAdapter`, `adapters/llm/ollama/runtime_status.py → OllamaLlmRuntimeStatusAdapter`; Ollama credential leaf zero
- provider-parameterized `LlmCredentialPort` / `LlmRuntimeStatusPort` production binding exactly one Router each; Application/API direct provider leaf selection zero
- concrete external API provider/model identity is not inferred from Repository Architecture; hard-coded Core/Application/Agent default provider/model absent current 10/13 Release selection = zero
- `WorkflowExecutionPort` production binding exactly one background executor; FastAPI direct background primitive/LangGraph executor selection zero
- Confirmation wire/controller closure: `PendingInterruptResponseV1` exact projection + `run.confirm_run`; undefined legacy interrupt DTO alias current reference zero
- connector-neutral circuit keys: provider-specific Core circuit enum values zero; Connector circuit identity carries connector_id

Architecture enforcement complements, but does not replace, behavioral tests. Enforcement allowlists may only encode exceptions already present in the Repository Architecture Exception Registry; an enforcement-only exception is itself a contract violation.

## Structural closure enforcement gate

The final architecture suite must prove both presence and absence. Positive discovery of canonical files is insufficient.

Required final checks include:

- canonical required-operation manifest exact-set coverage;
- one live production authority per capability;
- intended production caller closure across API, LangGraph, composition, and other production orchestrators;
- old production caller/import path zero for migrated capabilities;
- concrete barrel export zero for migrated authorities;
- Application root broad semantic module zero;
- legacy `application/workflows/**` production authority zero;
- final `read_*` / `write_*` compatibility facade zero when it exposes migrated concrete authority;
- `_compat` zero on `main`;
- banned filename/version-suffix detection with only Exception Registry allowances;
- Agent operation-per-file coverage against the current 06/15 semantic responsibility set;
- unit-test canonical owner-path coverage and legacy test-import zero;
- Application forbidden dependency checks for FastAPI responsibility, LangGraph routing responsibility, concrete Connector/MCP Adapter, Provider SDK/API client, and concrete SQLite adapter/direct SQLite access.

Architecture enforcement must classify old-path literals that exist solely inside negative enforcement tests as `EXPECTED_ENFORCEMENT`; they do not count as a live import/export/caller.

### Caller-closure proof

For each required Application capability, validation records at least:

```
capability
canonical owner module/symbol
expected production boundary callers
observed canonical callers
observed legacy callers
observed old imports/exports
canonical test owner
closure verdict
```

The capability passes only when expected callers are accounted for and legacy caller/import/export counts are zero.

### Final structural verdict

```
STRUCTURAL_CONTRACT_PASS
= naming/placement/dependency pass
+ required-operation manifest pass
+ single-authority pass
+ caller-closure pass
+ compatibility-zero pass
+ test-ownership pass
```

This structural verdict is necessary but does not replace behavioral regression required by 12 Test Design.

- repository callable closure: mutable lifecycle repositories expose only exact `update_if_version_and_status(...)` public mutation method; alias/command-specific repository mutation authority prohibited
- connector installation manifest closure: `installed_connector_manifest.json` rows/paths must match 10 contract + 16 connector package mapping and every installed artifact must be covered by verified Release Manifest hash
- signed Tool artifact closure: implementation Tool manifest set/fields == 07 current Registry rows; installed signed-tool-registry/projection hashes are Release-Manifest covered; Connector adapters import no `application/tool_registry/**`
- resume identity closure: semantic owner/profile→compiled subgraph mapping exact; `RegisteredResumeTargetRefV2` agent/main forms only; main resume stages exactly `RETRIEVAL_ENTRY|PLANNING_ENTRY|REVIEW_ENTRY|PREFLIGHT|READ_EXECUTION|VERIFICATION|RECOVERY|CANCEL_RESOLUTION`; external-control entry stages are issued only by the 06/07 handoff matrix, `PREFLIGHT` requires no in-flight Write Attempt, `READ_EXECUTION` requires Legacy READ Action EXECUTING + no ExecutionAttempt, and `ACTION_EXECUTION` is never resumable

- WEP ACCEPTED is not the durable linearization point: every WEP submission carries `WorkflowExecutionSubmissionV2(admission=...)` whose admission was already CAS-committed against handoff + Run authority versions; ACCEPTED requires no repository write.
