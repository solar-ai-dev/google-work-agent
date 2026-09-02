# MCP tool-use research prompt candidate v1

This directory is an **offline DRAFT candidate bundle** for the Google Work Agent's existing
21-slot Prompt Runtime contract. It does not replace the active Product prompt bundle and must
not be loaded by installed or production runtime before the normal activation gates pass.

## Why this is a candidate, not an active bundle

The Product is still before Prompt/Model experimentation. The current production baseline remains
the stable runtime-compatible control. This candidate incorporates research-informed hypotheses
about MCP tool discovery, state threading, long-horizon reliability, grounding, and adversarial
tool metadata/output. Those hypotheses must be measured against the existing baseline; they are
not evidence of improvement by themselves.

Every slot is therefore:

```text
status = DRAFT
node_dev_pass = false
node_holdout_pass = false
safety_gate_pass = false
manifest_approved = false
```

The committed source of this candidate is `candidate.json` plus `sources/`. The materializer
derives a normal `PromptRegistry` directory by overlaying the candidate onto the current active
21-slot manifest and copying the current input contract. This avoids duplicating Product-owned
slot metadata or turning Evaluation into a second Prompt Runtime authority.

## Materialize for an experiment

From the repository root:

```powershell
python evaluation/prompt_candidates/mcp-tool-use-2026-v1/materialize_prompt_candidate.py `
  --output <temporary-output-directory>
```

The temporary output contains:

```text
prompt_manifest.json
prompt_runtime_input_contract_v1.json
sources/<21 exact prompt-slot files>.md
```

`PromptRegistry.lookup_for_evaluation()` may load the resulting manifest. `PromptRegistry.lookup()`
must reject it because every generated slot remains `DRAFT`.

Do not materialize over:

```text
src/google_work_agent/application/prompt_runtime/
```

## Contract preservation

This bundle deliberately preserves:

- the exact 21 prompt-slot IDs;
- the current runtime-node mapping;
- the current input/output schema versions;
- the current prompt input allowlist/forbidden-field contract;
- the one-responsibility-per-node boundary;
- deterministic ownership of routing, policy, approval, execution, verification, and recovery.

It changes instruction text only. It does not add a new agent, tool-selection authority, policy
authority, state field, output field, or external-effect path.

## Research hypotheses encoded

The candidate tests whether explicit instructions improve:

1. exact selection from registered tool candidates rather than name similarity, list order, or
   persuasive descriptions;
2. preservation of opaque IDs/handles across calls without parsing, guessing, or cross-run reuse;
3. resistance to tool-description, tool-output, resource-content, error-message, and
   user-impersonation injections;
4. minimal-scope arguments and suppression of out-of-scope recipients, permissions, resources,
   and effects;
5. discovery-before-detail retrieval, high-signal context, and avoidance of redundant retries;
6. grounding in typed state and observed outcomes rather than an agent's or tool's success claim;
7. long-horizon consistency through bounded, delta-oriented retrieval/review behavior.

## Required evaluation before activation

Compare this bundle with the current active baseline using the same Product SHA, model candidate,
graph profile, dataset bytes, tool registry, fixtures, and graders.

Required gates:

- all 21 node DEV suites;
- all applicable node HOLDOUT suites;
- balanced should/should-not-call and should/should-not-confirm cases;
- MCP Security Bench-inspired attack cases covering name collision, preference manipulation,
  tool-description injection, out-of-scope parameters, user impersonation, false-error
  escalation, tool transfer, and retrieval injection;
- schema-valid-first-pass and repair-rate comparisons;
- tool-selection, argument, grounding, and review false-positive/false-negative metrics;
- Product-episode outcome verification rather than final-message claims;
- repeated trials with both pass@k and pass^k;
- the existing deterministic Product safety and real production-composition regression suites.

Only an immutable Product Decision/Prompt activation artifact may promote winning content to
`RUNTIME_ACTIVE`.

## Files

```text
candidate.json
materialize_prompt_candidate.py
research-basis.md
sources/<21 exact prompt-slot files>.md
```
