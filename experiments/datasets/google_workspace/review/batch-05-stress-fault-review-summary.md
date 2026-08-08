# Batch 05 · Stress 20 + Fault Safety 20 내부 검수

## Stress 20
- 10 Scenario Family × 2 Case
- Read 429·5xx Partial
- Reauth·MCP restart
- LLM AUTO fallback·Schema Repair
- Prompt Injection·Query Budget·Low Confidence
- Write pre-send failure
- CREATE·UPDATE UNKNOWN_RESULT recovered/unresolved
- Verification MISMATCH·Timeout
- Partial DAG·Cancel Partial

## Fault Safety 20
제품 장애를 Prompt 실패와 분리해 20개 Fault Profile로 정의했다. 비-LLM 오류는 LLM Revision을 금지하며, Retry·Recovery·End-state를 결정적 Grader로 검사한다.

## 판정
PASS
