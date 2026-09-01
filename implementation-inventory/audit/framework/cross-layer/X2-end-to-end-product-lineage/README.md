# X2 — End-to-End Product Lineage

Wave 1 freeze 후 scenario family별 requirement → entrypoint → state/effect → terminal projection lineage를 조사한다. framework 단계에는 scenario를 실행하지 않는다.

- scope: Answer-only, Read-only, approved Write, partial approval/rejection, FAILED retry, UNKNOWN_RESULT, verification mismatch, Recovery, Cancel, Reauth, Restart/Resume, Context Adjustment, retrieval cache loss, review back-edge, profile parity, API/Frontend trust, installed lifecycle
- exclusion: framework 단계 scenario 실행, lane-local semantics 재정의, 다른 X lane output 소비/수정
- namespace: `X2-E2E-*`
- future output: `runs/<AUDIT_SHA>/cross-layer/X2-end-to-end-product-lineage/`
