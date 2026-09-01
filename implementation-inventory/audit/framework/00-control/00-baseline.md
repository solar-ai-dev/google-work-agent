# Fixed Audit Baseline

- `PRODUCT_SOURCE_SHA`: `d58d2549b5022e8cca3683edc4aa06ea665cae7e`
- `AUDIT_SHA`: alias of `PRODUCT_SOURCE_SHA`; it is the run-directory and product-evidence key.
- `AUDIT_FRAMEWORK_SHA`: the exact commit containing the frozen Audit framework. The framework does not self-hardcode this SHA; the Coordinator records it in `runs/<AUDIT_SHA>/00-run-manifest.md` when the run is created.
- source repository: `google-work-agent`
- future run root: `implementation-inventory/audit/runs/<AUDIT_SHA>/`

## Checkout and parity rule

- worker는 시작 시 `HEAD == AUDIT_FRAMEWORK_SHA`와 clean worktree를 기록하되 source를 수정하지 않는다.
- Coordinator는 `PRODUCT_SOURCE_SHA..AUDIT_FRAMEWORK_SHA` diff가 `implementation-inventory/audit/**`에만 한정되는지 검증한다.
- 위 범위 밖 Product/Canonical/Test 파일이 하나라도 달라지면 해당 framework SHA는 이 Product baseline의 Audit에 사용할 수 없으며 새 `PRODUCT_SOURCE_SHA`를 freeze해야 한다.
- Product implementation evidence는 `PRODUCT_SOURCE_SHA`의 content와 동등한 source를 대상으로 한다. `implementation-inventory/audit/**`는 Audit metadata이며 Product implementation evidence가 아니다.

- historical rule: 기존 Audit의 PASS/CLEAN, row, finding, path, symbol, caller, test, package split은 current evidence로 상속하지 않는다.
- framework phase rule: 실제 Audit, test 실행, finding 판정, remediation을 수행하지 않는다.
