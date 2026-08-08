# fault_safety

Runtime·Provider·Persistence·Write Integrity 장애 평가 레이어.

- Fault Profile: 20
- Evaluation Item: 20
- 정상 사용자 요청 이후 발생하는 장애를 평가하며 `risky_user_requests`와 원인을 분리한다.
- `UNKNOWN_RESULT`, Verification `MISMATCH`, Auth, 429/5xx/Timeout, SQLite/Audit/MCP/SSE 계열을 포함한다.
