# 00-C. 핵심 정책·안전 불변조건 요약

> **R8.4 핵심 관점 문서** · 실제 권위는 01-B Policy, Domain 상태 전이, DB Constraint, 07 Interface, 09 Security가 소유한다.

## 1. 안전 모델

```text
Agent 제안
→ Domain·Policy 허용 판정
→ 사용자 승인
→ Claim V2
→ MCP 실제 인자 검증
→ Google Write
→ Google 재조회 Verification
→ 필요 시 Recovery
```

## 2. Approval과 Claim V2

승인은 “이 작업을 해도 된다”가 아니라 “이 정확한 Business Action을 실행해도 된다”는 Snapshot이다. `approval_arguments_hash`로 그 의미를 고정한다. 실제 Dispatch Payload는 별도 `execution_arguments_hash`로 고정하며 ClaimContextV2가 두 값을 함께 바인딩한다.

MCP는 서명·TTL·Process Instance·Action·Approval·Attempt·Tool·두 Hash·Nonce와 실제 수신 인자를 검증하기 전에는 Google Write를 호출하지 않는다.

## 3. UNKNOWN_RESULT / MISMATCH

- `UNKNOWN_RESULT`: 새 Write·새 Attempt·blind resend 금지. 기존 Google 결과 조회로 복구한다.
- `MISMATCH`: 자동 rollback·자동 수정 금지. `ACCEPT_PARTIAL` 또는 새 Corrective Plan만 허용한다.

## 4. Gmail 첨부파일

```text
수신: Gmail Attachment Metadata → 사용자 요청 → MCP Read → Download Stream
발신: 사용자 파일 → Local Staging → Descriptor·승인 → Claim V2 → MCP MIME Write
```

- bytes·파일 내용은 LLM Prompt·Context·Evidence로 보내지 않는다.
- bytes·Staging 원문·Local Path는 SQLite·Trace·Diagnostic Bundle에 저장하지 않는다.
- 발신 파일은 SHA-256 Descriptor로 승인하며 실행 직전 실제 bytes를 재검증한다.
