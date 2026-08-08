# Google Work Agent Experiment Pack v1.9.1 — Project-root ready

이 ZIP은 **Google Work Agent 저장소 루트에서 그대로 압축 해제**하는 배치용 Pack이다. `docs/` 파일은 포함하지 않는다.

주요 경로:

```text
experiments/
├─ datasets/google_workspace/
├─ user_prompts/
├─ graders/
├─ E01 ... E08
├─ G00, G01, G02, V01
├─ candidates/
├─ selections/
├─ runner/
└─ NEXT-CHAT-HANDOFF-v1.9.1.md

prompts/
└─ agent/
   ├─ request_understanding/
   ├─ acquisition/
   ├─ context_retriever/
   ├─ work_analysis/
   ├─ planning/
   ├─ review/
   ├─ assembled/
   └─ prompt-manifest-v0.7.json
```

**주의:** 기존 같은 경로에 작업 파일이 있으면 덮어쓰기 전에 Git diff를 확인한다. 실제 Windows repository에는 이 Pack을 내가 직접 적용하지 않았다.
