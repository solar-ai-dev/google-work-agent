# 00-B. 평가·실험 전략과 선택 이유

> **R8.4 핵심 관점 문서** · 실험의 권위 계약은 13, Prompt·Failure 정규화는 15, 제품 회귀는 12가 소유한다.

## 1. 평가 순서

```text
Dataset·Grader Integrity
→ Safety / Write Integrity Hard Gate
→ Business Task Success
→ Process 원인 분석
→ Efficiency 비교
→ Reliability / Holdout / Stress
→ Product Decision
```

안전 실패는 비용·Latency·문장 품질로 보상하지 않는다.

## 2. P0 실험 질문

E01 Model·Runtime, E02 Prompt·Schema·Repair, E03 Node·Handoff, E04 Acquisition, E05 Retrieval, E06-A Native 1/3/6, E06-B Controlled post-retrieval decomposition, E07 Routing·Skip, E08 Review의 질문을 분리한다.

## 3. R8.4 안전 Gate 추가

`G02 Fault·Recovery·Write Integrity`에서 다음을 결정적으로 검증한다.

- Claim V2 Signature·Version·TTL·Service/MCP Instance·Action/Approval/Attempt/Tool Binding
- `approval_arguments_hash` / `execution_arguments_hash` 분리
- MCP 실제 Arguments 재해시
- one-time Nonce
- Attachment Download/Stage/Write isolation
- 첨부파일 bytes의 LLM·Context·SQLite·Trace 유입 0

첨부파일 bytes 자체는 Model·Prompt·Retrieval 성능 입력으로 사용하지 않는다.
