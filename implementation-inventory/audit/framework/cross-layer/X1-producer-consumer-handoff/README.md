# X1 — Producer / Consumer / Handoff

Wave 1 freeze 후 producer → output contract → persistence/revision/hash → consumer → input contract의 cross-layer closure를 조사한다.

- scope: API → Application → Agent → LangGraph; Retrieval → Analysis → Planning → Review → Persistence; Approval → Claim → Attempt → Connector → Verification; Recovery → Planning; Terminal → API/SSE/Frontend
- exclusion: lane-local 의미 재정의, 새 production owner 판정, 다른 worker output 수정
- namespace: `X1-PC-*`
- future output: `runs/<AUDIT_SHA>/cross-layer/X1-producer-consumer-handoff/`
