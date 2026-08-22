# Google Work Agent — Project Source Guide

**Canonical snapshot coordination guide — 2026-08-22**

## Concern authority

```text
제품 목표·범위          → 01 PRD
사용자 기능 동작        → 01-A Functional
안전·금지·승인 정책     → 01-B Policy
UI·UX                   → 02 UI·UX
시스템·레이어 경계       → 03 Architecture
영속 사실·상태 전이     → 04 Domain·DB + State Contract + SQL Constraint
Retrieval               → 05
Agent·Workflow runtime  → 06
Tool·MCP·내부 Interface → 07
시퀀스                  → 08
보안                    → 09
환경·배포               → 10
관측성                  → 11
제품 회귀 검증          → 12
후보 비교·실험          → 13
운영                    → 14
Prompt·Failure          → 15
Repository placement/naming/import-export enforcement/single production authority → 16
```

03 owns system/layer dependency semantics. 16 owns how those constraints are realized and enforced in repository paths/imports/exports and may not relax 03.

06/15 own versioned runtime Node/Agent/Prompt identifiers. Current heavy-Agent atomic responsibility IDs are versioned by Workflow v7.22 / Prompt Contract v1.28. Repository Architecture v1.4 maps those semantic capabilities to canonical repository owner/path/file/symbol names and does not independently rename a runtime contract ID.

For repository naming/placement questions, **16 is the single concern authority**. Other Project Sources may define semantic identifiers they own, but they must not introduce an independent repository path/file/symbol naming rule. Such references are mappings to 16 unless the owning semantic contract itself is being versioned.

## Project Source count

Final Project Source count is **29**. Project Source에는 21개 non-migration canonical source와 startup이 실제 자동 discovery·적용하는 executable Migration `0001~0008` 8개를 포함한다. `0006_plan_aggregate_invariants.sql`, `0007_connector_neutral_persistence.sql`, `0008_resource_ref_connector_identity.sql`도 현재 executable authority이므로 inventory에서 제외할 수 없다. Canonical executable migration path는 `src/google_work_agent/adapters/persistence/migrations/**`이며 startup discovery package는 `google_work_agent.adapters.persistence.migrations`다. `docs/database/migrations/**`는 documentation/reference mirror 역할일 뿐 executable migration inventory 또는 startup authority가 아니다. The subordinate pages under 16 are normative detail but are not separate Project Source entries.

## Version rule

The 2026-08-22 Repository Architecture convention itself changed repository organization/naming authority, Local-SLLM responsibility decomposition changed owned workflow/prompt behavior, and executable migration reconciliation restored the actual startup DB truth. Therefore versions are split by concern: Repository Architecture v1.4; Domain·DB v1.21 / DB Schema v1.9; Workflow v7.22; Sequence v3.19; Test v3.41; Evaluation v3.28; Prompt·Failure v1.28; Project Overview v1.18. Unaffected behavior documents retain their previous versions. Export/sync errata that only remove stale contradictory wording are sync corrections, not hidden behavior changes.

Repository Architecture version increments are required when repository naming/placement grammar, built-in exceptions, dependency realization, or production-authority rules change. Subordinate pages under 16 must identify the same parent version; stale parent-version references fail the documentation version-management gate.

## Structural refactor gate

```text
DOCUMENT_AUTHORITY_PRIORITY_PASS
DOCUMENT_PURPOSE_SCOPE_PASS
DOCUMENT_VERSION_MANAGEMENT_PASS
DOCUMENT_FORMAT_CONSISTENCY_PASS
SEMANTIC_TERMINOLOGY_CONSISTENCY_PASS
CROSS_REFERENCE_VALIDITY_PASS
TRACEABILITY_COMPLETENESS_PASS
NO_DUPLICATE_AUTHORITY_PASS
```

Only after all pass may `ARCHITECTURE_RULESET_FROZEN` and `READY_FOR_STRUCTURAL_REFACTOR` be declared.
