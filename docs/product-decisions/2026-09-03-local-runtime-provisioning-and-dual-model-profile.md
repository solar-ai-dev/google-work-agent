# Product Decision — Automatic Local Runtime Provisioning and Dual-Model Profile

- **Decision date:** 2026-09-03
- **Status:** `DIRECTION_APPROVED / RELEASE_ACTIVATION_GATED`
- **Branch:** `design/local-runtime-provisioning-profile-v1`
- **Product:** Google Work Agent

## 1. Decision

`LOCAL_CAPABLE` no longer requires the user to install Ollama or approved local models manually.

The Google Work Agent installation and first-run onboarding flow coordinates provisioning of:

1. a release-approved Ollama runtime; and
2. a signed Local Model Profile containing the models required by the product.

Ollama remains a separate local Loopback runtime process. It is not linked into Product Core and is not treated as an Application, Agent, or Domain owner.

The Windows Installer declares and installs the provisioning capability, but it does not embed the Ollama executable or large model weights. First-run provisioning downloads, verifies, installs, and prepares only artifacts authorized by the verified Release Manifest, `ModelManifestV2`, and `LocalModelProductDecisionV2` chain.

## 2. Candidate Local Model Profile

```text
profile_id = qwen3_5_dual_tier_candidate_v1
runtime    = OLLAMA
WORKER     = qwen3.5:4b
REASONING  = qwen3.5:9b
```

This concrete profile is direction-approved as the next evaluation candidate. It is not an active production or signed Release authority until the required Evaluation, Safety, hardware, provisioning, and Release gates pass.

`qwen2.5:7b` remains a single-model comparison baseline. It is no longer treated as the immutable product architecture.

## 3. Model Selection Boundary

Product LLM callers do not select a concrete model. They submit only:

```text
InferenceTierV1 = WORKER | REASONING
```

`StructuredInferenceRuntimeRouter` is the single authority that resolves an inference tier through `LocalModelProductDecisionV2.active_profile` and validates the resolved model against `ModelManifestV2`.

The following are prohibited as competing model-selection authorities:

- Agent code branching on model names;
- Prompt text requesting a larger or different model;
- Browser-provided model IDs or tags;
- provider leaf adapters choosing a model tier;
- model-name string parsing such as `4b`, `7b`, or `9b` to grant execution eligibility;
- a second model registry in Settings, Application, or Frontend.

## 4. Initial Tier Candidate Mapping

| Tier | Candidate responsibilities |
| --- | --- |
| `WORKER` | `request.identify_goal` and other bounded extraction/classification slots only after slot-specific Contract and Gold gates pass |
| `REASONING` | `request.detect_ambiguity`, Tool Routing semantic selection, Retrieval planning/sufficiency, Work Analysis, Planning, and Review |

The mapping is signed release data rather than Agent code. A Prompt slot may move between tiers only through evaluation and a new signed Product Decision/Profile revision.

The current repeated Confirmation defect makes `request.detect_ambiguity` a required `REASONING` evaluation case. The profile must prove forward progress rather than merely produce schema-valid output.

## 5. User Experience

The target first-run experience is:

```text
Install Google Work Agent
→ run environment and disk checks
→ reuse compatible existing Ollama OR prepare approved Ollama
→ download and verify the WORKER model
→ download and verify the REASONING model
→ run tier-specific Structured Output smoke tests
→ enable LOCAL_GPU
→ READY
```

The user does not execute `ollama pull`, use a terminal, select a model tag, or locate a separate installer.

The onboarding UI exposes:

- current component and stage;
- progress percentage and transferred/remaining bytes where available;
- `빠른 모델` and `고성능 모델` labels in the primary UX;
- exact model ID, digest, and runtime version only in diagnostics;
- typed retryable failure actions;
- `다시 시도`, `진단 열기`, and `API로 계속` when allowed.

## 6. Non-Destructive Ollama Ownership

Provisioning distinguishes:

```text
OLLAMA_ORIGIN = PREEXISTING | PRODUCT_PROVISIONED
MODEL_ORIGIN  = PRODUCT_PROVISIONED
```

Rules:

- compatible `PREEXISTING` Ollama is reused;
- a pre-existing shared runtime is not silently upgraded, stopped, or uninstalled;
- product shutdown does not force-stop a shared Ollama process;
- runtime/model updates occur only through a signed product upgrade or explicit repair flow;
- default uninstall preserves pre-existing Ollama;
- deletion of product-provisioned model data requires an explicit uninstall option;
- partial downloads use bounded staging and crash-safe reconciliation rather than duplicate downloads.

## 7. Security and Supply-Chain Rules

Provisioning is a deterministic `SYSTEM` operation, not an LLM Tool.

Only the verified Release Manifest → `ModelManifestV2` + `LocalModelProductDecisionV2` chain may supply:

- Ollama installer source reference;
- supported runtime version;
- installer signature and SHA-256 expectation;
- model ID and resolved digest;
- model parameter class and download size;
- active Local Model Profile and tier bindings.

Browser input, Prompt output, Connector content, and arbitrary environment values cannot provide a download URL, executable path, shell argument, model tag, or digest.

Signature/hash/digest mismatch fails closed before Local inference is enabled.

## 8. Typed Runtime and API Contract

The Local API adds:

```text
POST /api/v1/runtime/local/provision
```

The command carries only a versioned schema and server-adjudicated `command_id`. The Browser does not submit artifact identity.

`RuntimeDetailResponseV2` projects a bounded `LocalRuntimeProvisioningStatusV1` containing:

- overall status;
- Runtime origin;
- active profile ID;
- per-component status/progress;
- typed error code;
- retryability.

`StructuredInferenceRequestV2` adds `InferenceTierV1`; `StructuredInferenceResultV2` returns bounded actual runtime/provider/model/profile/tier metadata.

## 9. Canonical Repository Mapping

```text
application/use_cases/runtime_status/provision_local_runtime.py
→ ProvisionLocalRuntimeCommandV1
→ ProvisionLocalRuntimeResultV1
→ ProvisionLocalRuntimeHandler

ports/system/local_runtime_provisioning_port.py
→ LocalRuntimeProvisioningPort

adapters/system/ollama_local_runtime_provisioning.py
→ OllamaLocalRuntimeProvisioningAdapter

installer/windows/local_runtime_provisioning_definition.py
→ WindowsLocalRuntimeProvisioningDefinition

src/google_work_agent/ports/llm/approved_model_manifest.py
→ ApprovedModelEntryV2 / ModelManifestV2

src/google_work_agent/ports/llm/local_model_product_decision.py
→ LocalModelTierBindingV1 / LocalModelProfileV1 / LocalModelProductDecisionV2

release/generate_model_manifest.py
→ ModelManifestV2 materialization

release/generate_local_model_product_decision.py
→ LocalModelProductDecisionV2 materialization
```

Existing `runtime_status.get_runtime_status` remains the only runtime-status projection authority. No new `model`, `ollama`, `provisioning`, or generic `runtime` Application owner is created.

`OllamaLocalRuntimeProvisioningAdapter` is the only concrete owner of download, staging, signature/hash/digest verification, existing-runtime detection, controlled installer invocation, readiness checks, model preparation, and operational reconciliation.

## 10. Evaluation and Release Gate

Paired candidates:

```text
L0 = qwen2.5:7b single-model baseline
L1 = qwen3.5:9b single-model candidate
L2 = qwen3.5:4b WORKER + qwen3.5:9b REASONING candidate
```

The comparison keeps PromptRef, schemas, policy, Tool Registry, fixtures, Domain behavior, and Graph topology fixed.

Required evidence includes:

- schema-valid first pass and repair rate;
- semantic accuracy;
- selected-resource preservation;
- over-confirmation and repeated-question rate;
- forward-progress rate;
- Tool Route and Retrieval quality;
- Planning/Review quality;
- actual Gmail READ reachability;
- approval-gated Gmail WRITE and Verification;
- model load/swap overhead;
- peak VRAM/RAM and throughput;
- p50/p95 Node and total Run latency;
- cold provisioning time and download volume;
- interrupted-download recovery;
- clean-VM, upgrade, repair, and uninstall behavior.

Release activation requires:

```text
12 Safety Regression = 100%
AND required Node Contract Gate PASS
AND no-progress / repeated Confirmation Gate PASS
AND E2E BTS threshold PASS
AND Gmail READ/WRITE safety path PASS
AND target hardware resource/latency Gate PASS
AND clean provisioning/upgrade/uninstall Gate PASS
AND signed Release + ModelManifestV2 + LocalModelProductDecisionV2 materialization
```

Parameter count or model tag alone never grants support.

## 10-A. Versioned artifact cut-over

The current implementation has `ModelManifestV1` and `LocalModelProductDecisionV1` with single-model semantics. The dual-tier design is an incompatible contract change and therefore targets V2 artifacts rather than mutating V1 fields in place.

Final activation requires:

```text
model-manifest-v2.json + ModelManifestV2 parser/generator
local-model-product-decision-v2.json + LocalModelProductDecisionV2 parser/generator
all provisioning/router/composition callers moved to V2
V1 production readers/exports/artifacts = 0
mixed V1/V2 release = prohibited
```

V1 may remain only in explicit migration/fixture evidence.

## 11. Implementation Waves

1. **Contract realization** — typed API/Port/Profile schemas, Model Manifest extension, architecture tests.
2. **Provisioning adapter** — download/staging/signature/hash/digest, existing-runtime detection, operation replay reconciliation.
3. **Installer and onboarding** — clean-VM first-run progress, retry, repair, and uninstall behavior.
4. **Tier routing** — Prompt-slot tier metadata and Router profile resolution with no Agent hardcoding.
5. **Evaluation** — L0/L1/L2 comparison, repeated Confirmation reproduction, Gmail READ/WRITE E2E.
6. **Release** — signed Model Manifest/Profile and clean-VM/upgrade/uninstall gates, followed by activation.

## 12. Explicit Non-Closure

This decision and Canonical synchronization do not claim that:

- automatic Ollama/model provisioning is implemented;
- the dual-model profile has passed Evaluation;
- `qwen3.5:4b` or `qwen3.5:9b` is already a signed production default;
- the current Request Understanding Confirmation loop is fixed;
- actual Gmail Agent READ/WRITE has reached the Connector boundary.

Those remain implementation and runtime-closure work.