# Prompt Bundle

최신 Prompt Manifest: `prompt-manifest-v0.7.json`

완료 Agent:
- Request Understanding
- Acquisition
- Context Retriever
- Work Analysis
- Planning
- Review

모든 Prompt는 아직 `DRAFT`다. DEV → Node HOLDOUT → Safety Gate 통과 전 Runtime 활성화 금지.
Failure-specific Prompt는 Base + Purpose/Repair/Reassess/Revise + Failure Block 조립 방식이다.

R7 rebase: Planning supports READ/CREATE/UPDATE/SEND/DELETE; Request Understanding preserves SEND intent and true forbidden scope; Work Analysis applies overlap != conflict. All slots remain DRAFT.
