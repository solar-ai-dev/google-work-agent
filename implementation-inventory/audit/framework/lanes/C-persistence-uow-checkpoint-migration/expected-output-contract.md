# Expected Output Contract

미래 `runs/<AUDIT_SHA>/lanes/C-persistence-uow-checkpoint-migration/`에 `00-lane-baseline.md`, `01-requirements.csv`, `02-implementation-evidence.csv`, `03-negative-evidence.csv`, `04-duplicate-authority.csv`, `05-findings.csv`, `06-unchecked.csv`, `07-lane-report.md`만 쓰며 CSV schema는 `framework/templates/`를 따른다.

requirement ID는 `C-PER-*`이다. SQL/schema row는 구현 evidence이며 독립 behavior authority로 기록하지 않는다.
