# Expected Output Contract

미래 `runs/<AUDIT_SHA>/lanes/A-product-requirements-policy-ux/`에만 `00-lane-baseline.md`, `01-requirements.csv`, `02-implementation-evidence.csv`, `03-negative-evidence.csv`, `04-duplicate-authority.csv`, `05-findings.csv`, `06-unchecked.csv`, `07-lane-report.md`를 쓴다.

CSV는 `framework/templates/` schema를 그대로 사용하고 ID는 `A-FUNC-*` 및 lane-local evidence/finding namespace를 사용한다. 현재 framework 단계에는 이 파일들을 생성하지 않는다.
