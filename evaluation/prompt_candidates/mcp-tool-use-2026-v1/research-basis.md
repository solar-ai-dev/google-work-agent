# Research basis and slot-level application

## Status

This document records the external evidence used to form a **testable prompt candidate**. It does
not claim that the candidate is better than the current baseline. The Product's own Canonical
contracts remain authoritative whenever an external recommendation conflicts with them.

Research reviewed through 2026-09-02.

## Primary evidence

| Source | Relevant result | Candidate implication |
|---|---|---|
| [MCP 2026-07-28 specification release](https://blog.modelcontextprotocol.io/posts/2026-07-28/) | The protocol core becomes stateless; applications should mint explicit state handles and pass them back across calls. Multi-round input uses an originating-request-bound opaque state value. | Preserve opaque IDs exactly, never infer hidden session state, and keep confirmation/retry state bound to the current Run. |
| [MCP Tools specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) | Tool inputs and outputs require validation; annotations are untrusted unless the server is trusted; sensitive operations require user control. | Typed registry fields outrank prose, tool output is not approval, and write scope cannot expand through metadata. |
| [MCP tool-annotation risk guidance](https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/) | Annotations are hints, not enforcement, and do not make models resistant to prompt injection. | Prompts must not treat annotations or descriptions as authorization or safety guarantees. Deterministic Product policy remains authoritative. |
| [Anthropic: Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents) | Effective tools are distinct, high-signal, composable, precisely described, and improved through real multi-step evaluation. IDs, filtering, pagination, concise responses, and actionable errors matter. | Select only exact registered candidates, keep queries narrow, preserve IDs, avoid overlapping interpretation, and request only useful deltas. |
| [Claude Tool Search](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool) | Large tool catalogs degrade selection accuracy and inflate context; focused discovery loads only a small relevant subset. | Use the eligible capability projection as the closed candidate universe and avoid selecting from irrelevant tools or name similarity. |
| [Anthropic: Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) | Agent evaluation should distinguish task, trial, transcript, and outcome; run repeated trials; balance positive/negative cases; verify environment state rather than claims. | Prompts distinguish claimed success from verified state; activation requires outcome-grounded, repeated evaluation. |
| [MCP-Bench](https://arxiv.org/abs/2508.20453) | 28 live servers and 250 tools expose persistent difficulty in fuzzy tool discovery, exact parameters, multi-hop planning, cross-tool coordination, and grounding in intermediate outputs. | Harden tool selection, parameter scope, intermediate-output grounding, and long-horizon delta tracking. |
| [MCPMark](https://arxiv.org/abs/2509.24002) | 127 stateful CRUD tasks show low pass@1/pass^4 and long trajectories averaging many turns and tool calls. | Prefer bounded, non-redundant retrieval/review and evaluate consistency, not one lucky completion. |
| [MCP Security Bench](https://arxiv.org/abs/2510.15994) | Real MCP attacks include name collision, preference manipulation, tool-description injection, out-of-scope parameters, user-impersonating responses, false-error escalation, tool transfer, and retrieval injection. | Add explicit rejection rules at planning, selection, evidence, argument, and review stages. |
| [MCPSecBench](https://arxiv.org/abs/2508.13220) | A 17-attack taxonomy across four MCP attack surfaces compromised at least one tested platform in most attack classes. | Treat prompt-only defenses as one layer and preserve deterministic validation, authorization, and sandbox boundaries. |
| [Google Maps Grounding MCP integration guidance](https://developers.google.com/maps/architecture/grounding-with-maps-mcp) | Precise constraints, discovery-before-detail, and exact reuse of tool-returned IDs reduce structural hallucination. | Use precise query constraints and never synthesize resource identifiers. |
| [OpenAI: A practical guide to building agents](https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/) | Guardrails should be layered with authentication, authorization, access control, bounded retries, and human intervention for high-risk actions. | Prompts do not replace Product policy; confirmation and failure thresholds remain deterministic gates. |

## Slot-level changes

| Slot family | Research-informed additions | Existing authority preserved |
|---|---|---|
| Request Understanding | Reject user impersonation from connector content; preserve opaque refs; ask only for genuine user-owned choices; never ask for credentials. | User intent extraction only; no tools, retrieval, policy, or arguments. |
| Tool Routing | Use typed eligible candidates; reject name collision, list-order bias, persuasive descriptions, and scope expansion. | Frozen connector/resource/effect and deterministic registry validation. |
| Retrieval | High-signal discovery-before-detail; exact route/segment IDs; no repeated equivalent query without a named delta; tool output is untrusted data. | Deterministic query construction, pagination, continuation, and budgets. |
| Work Analysis | Separate quoted claims from authoritative facts; reject hidden instructions, identity claims, and unverified success; preserve evidence IDs. | Candidate extraction only; deterministic validation owns truth/policy. |
| Planning | Minimal scope and schema fields; no invented IDs, recipients, permissions, or effects; no claim of successful execution. | Frozen route/tool/effect and deterministic approval/execution. |
| Review | Detect unsupported claims, invented IDs, route drift, scope expansion, parameter abuse, user impersonation, and instruction leakage only within each inspector's assigned dimension. | Review does not mutate, route, enforce policy, or execute. |

## Explicit non-adoptions

The candidate does **not**:

- copy any benchmark's prompt;
- add chain-of-thought requirements;
- expose raw MCP/provider payloads, continuations, Gold, or grader feedback;
- make tool descriptions or annotations an authorization source;
- allow a Prompt to select policy, approve a write, execute a tool, verify an effect, or recover a Run;
- hard-code a final model, provider, graph profile, or sampling configuration before Product Decision;
- promote itself to runtime based on source review alone.

## Evaluation notes

A prompt change can trade utility for refusal or over-confirmation. Security cases must therefore
be paired with benign controls that use similar vocabulary. Review false positives, unnecessary
retrieval, unnecessary confirmation, token cost, and latency are first-class regression metrics.
