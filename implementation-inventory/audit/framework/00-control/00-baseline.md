# Fixed Audit Baseline

- `AUDIT_SOURCE_SHA`: `d58d2549b5022e8cca3683edc4aa06ea665cae7e`
- source repository: `google-work-agent`
- future run root: `implementation-inventory/audit/runs/<AUDIT_SHA>/`
- baseline rule: worker는 시작 시 `HEAD == AUDIT_SHA`와 clean worktree를 기록하되 source를 수정하지 않는다.
- historical rule: 기존 Audit의 PASS/CLEAN, row, finding, path, symbol, caller, test, package split은 current evidence로 상속하지 않는다.
- framework phase rule: 실제 Audit, test 실행, finding 판정, remediation, commit, push를 수행하지 않는다.
