# CURRENT — R8.2 Business-ready Dataset / Prompt Pack

- Dataset: `rebuild-v1.13-r8.3`
- Prompt bundle: `0.8.2-r8.3`
- Semantic responsibility bundle: `semantic-r8.3-v1`
- Canonical cases: Core 60 + Holdout 12 + Stress 20 = 92
- Canonical Korean user requests were naturalized without changing their Gold intent/action contract.
- Short fixture email bodies were enriched with realistic business wrappers while preserving the original fact sentences verbatim.
- Prompt Manifest input schemas are concrete files; no `contracts/...` phantom schema path is active.
- Failure reason is prompt-assembly metadata, not Runtime Prompt Slot identity.
- E06-A and E06-B are separate; E06-B starts at `CONTEXT_READY_V1` with Google Read 0.
- Model execution has not been performed; changed prompts remain DRAFT.
