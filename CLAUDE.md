Google Work Agent — Claude Code Instructions

Purpose

This file defines how Claude Code should work in this repository.

It does not replace product, architecture, policy, domain, interface, security, test, or evaluation documents.Do not duplicate detailed contracts here.

When implementation details matter, read the current Canonical documents in docs/.

Communication

Respond to the user in Korean unless the user requests another language.

Keep explanations concise and engineering-focused.

Clearly separate:

current repository facts,

canonical document requirements,

implementation gaps,

assumptions or recommendations.

Source of truth

Before substantial work:

Inspect the actual repository.

Read docs/00-PROJECT-SOURCE-GUIDE.md.

Identify the Canonical owner of the concern being changed.

Read only the related documents and tests needed for that concern.

Use:

Canonical documents to understand how the system should behave.

Source code, tests, migrations, and configuration to understand what is implemented now.

If they disagree, do not silently choose one.Identify the mismatch and resolve it according to the documented concern ownership.

Do not invent missing contracts.

Working method

Before editing:

inspect Git status and current branch;

locate the relevant implementation;

locate existing tests;

understand current dependency direction and boundaries;

determine the smallest correct change.

Prefer modifying existing patterns over introducing parallel abstractions.

Do not redesign unrelated parts of the system as incidental cleanup.

Do not implement something that already exists without first confirming the actual gap.

Architecture

Preserve the current architectural boundaries and dependency direction.

General principle:

UI
→ Local API
→ Application / Workflow
→ Domain / Policy
→ Adapters
→ External Systems

Responsibilities should remain in their owning layer.

In particular:

UI must not bypass backend/domain boundaries.

API handlers must not replace domain rules.

Workflow or Agent code must not become the authority for deterministic product state.

LLM reasoning must not replace deterministic policy, authorization, state-transition, execution, verification, or recovery rules.

External adapters must not bypass upstream safety contracts.

When adding a feature, fit it into the existing architecture unless the Canonical architecture itself is intentionally being changed.

Safety and external effects

Treat operations that can change external state as safety-sensitive.

Follow the current Canonical contracts for:

authorization and approval;

execution authority;

argument integrity;

idempotency;

delivery uncertainty;

verification;

recovery;

cancellation.

Do not weaken these contracts for convenience.

Do not treat an external API response alone as proof that the intended product state is correct when the Canonical design requires verification.

When execution outcome is uncertain, preserve uncertainty and follow the defined recovery path rather than blindly repeating side effects.

State and persistence

Treat Domain state and persistent data as authoritative according to the Canonical Domain contracts.

Do not invent undocumented states or transitions.

Do not mutate persistent state from inappropriate layers.

Preserve optimistic concurrency and command/idempotency rules where defined.

Keep database transactions short.

Do not hold a database write transaction open while waiting on external or long-running I/O.

Migrations are historical artifacts.

Do not rewrite existing migrations to represent a new change.Add a new migration only when the current schema genuinely requires one.

Agent and LLM behavior

Use LLMs for responsibilities that require interpretation or reasoning.

Keep deterministic responsibilities in deterministic code.

Agents should follow the current Workflow and Prompt contracts rather than creating new routing, memory, tool, or state semantics.

Do not:

let Agents bypass the Supervisor/Application boundaries;

move policy or execution authority into prompts;

inject evaluation gold, grader answers, or hidden benchmark information into product prompts;

add long-term Agent memory unless explicitly defined by the Canonical design.

Data and secrets

Minimize sensitive data exposure.

Never intentionally expose secrets or private user data through:

source code,

commits,

logs,

traces,

test output,

diagnostics,

prompts,

generated documentation.

Use the repository's fake/stub/synthetic test infrastructure where possible.

Do not use real credentials or live user data for ordinary automated tests.

Do not perform live destructive or externally visible actions unless the user explicitly requested the live operation.

Scope discipline

Make the smallest complete change that satisfies the request and the Canonical contracts.

Avoid:

unrelated refactors;

broad renames;

dependency-wide upgrades;

architecture redesign outside the requested concern;

large formatting-only diffs;

weakening tests to make code pass;

temporary workarounds presented as permanent design.

If multiple files are genuinely affected by one contract, update the necessary set rather than forcing the change into one file.

Frontend

When changing frontend code:

follow the current UI/UX document;

inspect the existing component/state patterns first;

use the documented Local API contract;

do not make frontend state authoritative for backend/domain facts;

do not mix a visual-only task with backend/domain redesign unless the contract requires both.

Testing

Use the repository's actual configured commands.

Do not guess script names.

Run:

focused tests for the changed behavior;

relevant contract/integration tests;

broader regression checks appropriate to the change.

If the repository defines lint, formatting, type-check, build, or other gates relevant to modified code, run them before declaring completion.

Do not claim completion while a relevant safety, state, interface, or regression test is failing.

Repository hygiene

Unless explicitly requested:

do not commit;

do not push;

do not merge or rebase;

do not change branches;

do not use destructive Git commands.

Do not create root-level:

changelogs,

handoff files,

status reports,

scratch documents,

temporary design summaries.

Keep work inside the existing repository structure.

When blocked or uncertain

Investigate before asking the user.

Check:

existing code,

tests,

migrations,

configuration,

Canonical documents.

If a required contract is still missing or contradictory:

do not invent a new one;

identify the exact ambiguity;

preserve the safer existing behavior;

explain which Canonical concerns are affected.

If a true contract change is required, identify its impact before implementing it.

Completion report

At the end of a coding task, report concisely:

what changed;

files changed;

important contract or boundary preserved;

tests/checks executed and results;

remaining manual/live verification;

any repository-vs-document mismatch discovered.

Do not create a separate report file unless explicitly requested.

Core principle

Prefer:

contract consistency, deterministic safety, recoverability, minimal change, and verifiable behavior

over convenience, speculative redesign, or shorter code.