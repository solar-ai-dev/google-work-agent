# Parallel Execution Plan

1. Coordinator가 `PRODUCT_SOURCE_SHA`(`AUDIT_SHA`), `AUDIT_FRAMEWORK_SHA`, clean framework checkout, authority manifest, run directory를 freeze한다.
2. Coordinator가 `PRODUCT_SOURCE_SHA..AUDIT_FRAMEWORK_SHA` diff가 `implementation-inventory/audit/**`에만 한정됨을 검증하고 그 결과를 `00-run-manifest.md`에 기록한다.
3. 모든 worker는 `AUDIT_FRAMEWORK_SHA`를 checkout하고 `HEAD == AUDIT_FRAMEWORK_SHA` + clean worktree를 기록한다. Product evidence target은 `PRODUCT_SOURCE_SHA`다.
4. Wave 1 A~L을 서로 다른 worker에 배정한다. R은 Product audit과 독립적으로 methodology만 조사한다.
5. 각 worker는 manifest의 exact `runs/<AUDIT_SHA>/lanes/<LANE-DIRECTORY>/`만 생성·수정한다.
6. worker는 lane output contract와 completion checklist를 자체 검증한 뒤 immutable handoff manifest를 제출한다.
7. Coordinator가 모든 Wave 1 output을 schema/ownership/ID/accounting 기준으로 merge하고 freeze한다.
8. Wave 2 X1~X4를 freeze된 Wave 1 결과에 대해 각 exact `runs/<AUDIT_SHA>/cross-layer/<X-DIRECTORY>/`에서 병렬 실행한다.
9. Coordinator가 Wave 2를 merge하고 uncovered, conflict, unchecked, unadjudicated duplicate를 계산한다.
10. 실제 completion verdict는 모든 gate가 끝난 별도 단계에서만 가능하다.

어떤 단계에서도 worker 간 직접 파일 수정, 공용 findings/coverage/evidence/summary 동시 쓰기, shared counter를 허용하지 않는다.

## Future run tree contract

실제 Audit을 시작할 때만 다음 SHA directory를 만든다. 여기서 `<AUDIT_SHA>`는 `PRODUCT_SOURCE_SHA`와 동일하다.

```text
runs/<AUDIT_SHA>/
├── 00-run-manifest.md
├── lanes/
│   ├── A-product-requirements-policy-ux/
│   ├── B-domain-lifecycle-invariants/
│   ├── C-persistence-uow-checkpoint-migration/
│   ├── D-application-execution-verification-recovery/
│   ├── E-agent-semantics-retrieval/
│   ├── F-langgraph-runtime-state-node-edge/
│   ├── G-ports-connectors-mcp-llm-system/
│   ├── H-api-composition-frontend/
│   ├── I-security-privacy-observability-operations/
│   ├── J-evaluation-prompt-evidence/
│   ├── K-launcher-installer-release-packaging/
│   ├── L-repository-architecture/
│   └── R-historical-audit-methodology/
├── cross-layer/
│   ├── X1-producer-consumer-handoff/
│   ├── X2-end-to-end-product-lineage/
│   ├── X3-test-evidence-non-vacuity/
│   └── X4-global-semantic-uniqueness/
└── coordinator/
```

Wave 1 worker는 자기 lane directory, Wave 2 worker는 자기 X directory, Coordinator는 `coordinator/`만 쓴다. `00-run-manifest.md` 생성과 `PRODUCT_SOURCE_SHA`/`AUDIT_FRAMEWORK_SHA` freeze는 Coordinator가 담당한다.
