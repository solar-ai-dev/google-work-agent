# Repository Coding Agent Instructions

## Purpose

This document defines how coding agents should work in this repository.

It does not replace product, architecture, policy, domain, interface, security, test, evaluation, or operational specifications.

Do not duplicate detailed contracts here.

When implementation details matter, read the current canonical documents and the actual repository.

---

## Communication

Use Korean as the default language for all user-facing communication.

This applies to:

* normal responses;
* progress updates;
* intermediate status messages;
* implementation notes;
* investigation summaries;
* test and validation reports;
* completion reports;
* explanations shown while work is in progress.

Do not switch to another natural language unless the user explicitly requests it.

Technical identifiers may keep their original form, including:

* source code;
* CLI commands;
* paths;
* class and function names;
* variable names;
* API names;
* schema fields;
* enum values;
* branch and commit identifiers;
* raw error messages when exact reproduction is necessary.

When technical text is quoted in another language, explain its meaning in Korean when explanation is needed.

Keep explanations concise and engineering-focused.

Clearly distinguish:

* current repository facts;
* canonical requirements;
* implementation gaps;
* assumptions;
* recommendations.

Language consistency is part of completion quality.

---

## Source of Truth

Before substantial work:

1. inspect the actual repository;
2. inspect the current branch and working tree;
3. identify the canonical owner of the concern being changed;
4. read only the specifications and tests relevant to that concern;
5. inspect the implementation that currently exists.

Use:

* canonical documents to determine how the system should behave;
* source code, tests, migrations, configuration, and runtime wiring to determine what is implemented now.

Do not assume that documentation describes the current implementation exactly.

Do not assume that implementation is correct merely because tests pass.

If documentation and implementation disagree:

* identify the mismatch;
* determine which concern owns the contract;
* preserve the safer existing behavior until the mismatch is resolved;
* do not silently invent a new contract.

---

## Working Method

Before editing:

* inspect repository status and current branch;
* locate the relevant implementation;
* locate existing tests;
* understand the current dependency direction;
* identify existing abstractions and module boundaries;
* determine the smallest complete change within the requested concern.

Do not implement something that already exists without confirming the actual gap.

Prefer extending or correcting existing patterns over creating parallel implementations.

Do not perform unrelated cleanup while changing another concern.

---

## Scope Discipline

Make the smallest complete change that satisfies the requested concern and its contracts.

"Minimal change" means the smallest complete change **inside the requested concern**.

It does not mean that a change must be limited to one file or one class.

When the user explicitly requests a structural refactor, a multi-file change is acceptable when necessary to correctly refactor that concern.

For an explicitly scoped refactor:

1. define the concern boundary first;
2. preserve behavior unless behavior change is explicitly requested;
3. change only components inside that concern or directly required boundaries;
4. validate incrementally;
5. do not expand into unrelated architecture.

Avoid:

* unrelated refactors;
* broad renames without architectural value;
* dependency-wide upgrades;
* speculative architecture redesign;
* large formatting-only diffs;
* weakening tests to obtain a passing build;
* temporary workarounds presented as permanent design.

If multiple files genuinely belong to the same contract, modify the necessary set rather than forcing the change into one location.

---

## Architecture

Preserve architectural boundaries and dependency direction.

General responsibility flow:

```text
User Interface
→ API / Delivery Boundary
→ Application / Workflow
→ Domain / Policy
```

External capabilities should follow dependency inversion:

```text
Application / Workflow
→ Port / Contract
← Adapter
→ External System
```

Concrete dependency construction happens separately:

```text
Composition Root
→ constructs implementations
→ connects dependencies
→ exposes completed application components
```

Responsibilities must remain with their owning layer.

In particular:

* presentation code must not bypass backend or domain boundaries;
* API handlers must not become domain services;
* workflow code must not become the authority for persistent product facts;
* model reasoning must not replace deterministic policy;
* model reasoning must not replace authorization;
* model reasoning must not replace state-transition rules;
* model reasoning must not replace execution authority;
* model reasoning must not determine whether an external side effect actually succeeded;
* external adapters must not bypass upstream safety contracts.

---

## Modularity

Prefer high cohesion and low coupling.

A module should own one clear capability or responsibility.

A module should perform work belonging to its own capability and should not absorb unrelated behavior merely because two operations appear in the same user flow.

Separate:

```text
capability implementation
use-case orchestration
dependency composition
```

A capability module should not know about unrelated sibling capability implementations.

Avoid lateral dependency chains such as:

```text
Capability A
→ Capability B
→ Capability C
→ Capability A
```

Prefer:

```text
              Application
             /     |      \
    Capability A   B       C
```

When multiple capabilities are required for one user-visible operation, coordinate them from the Application or Workflow layer.

Do not move orchestration into individual capability modules merely to reduce the number of application services.

---

## Module Ownership

Before placing logic in a module, determine who owns the responsibility.

Typical ownership:

* Domain: business invariants and state-transition rules;
* Policy: deterministic allow, block, approval, and safety rules;
* Application: use-case orchestration;
* Workflow: execution order and workflow routing;
* Port: capability contract;
* Adapter: integration-specific implementation;
* Persistence Adapter: storage translation;
* API Boundary: protocol translation and validation;
* Composition Root: construction and dependency wiring.

Do not place logic according to convenience or proximity.

Place it according to responsibility ownership.

---

## Dependency Inversion

Depend on stable contracts rather than concrete infrastructure implementations.

Prefer:

```text
Application
→ Contract
← Infrastructure Implementation
```

over:

```text
Application
→ Infrastructure Implementation
→ External SDK
```

Core business logic should not directly depend on:

* web frameworks;
* workflow runtimes;
* database adapters;
* provider SDKs;
* external API clients;
* operating-system-specific infrastructure;
* model-provider implementations.

External integrations should implement upstream contracts.

Do not create abstractions merely to increase abstraction count.

Introduce a Port or interface when there is a real boundary such as:

* an external system;
* a replaceable implementation;
* an independently testable capability;
* an architectural dependency boundary.

Do not introduce interfaces around pure internal implementation details with no meaningful replacement or boundary.

---

## Dependency Injection

Dependencies should normally be supplied explicitly.

Prefer:

* constructor injection;
* function parameter injection;
* explicit factories.

Avoid creating infrastructure dependencies inside business components when those dependencies can be supplied externally.

Bad pattern:

```text
Business component
→ creates database implementation
→ creates provider implementation
→ creates external client
```

Preferred pattern:

```text
Composition Root
→ creates implementations
→ injects required contracts
→ business component uses only those contracts
```

Inject only what a component actually needs.

Do not inject an entire dependency container into:

* domain objects;
* services;
* workflow nodes;
* agents;
* repositories;
* adapters.

Do not use the dependency container as a service locator.

Dependencies should remain visible from constructors or explicit function signatures.

---

## Composition Root

Concrete object construction and dependency wiring belong in a small, explicit Composition Root at the application startup boundary.

The Composition Root may:

* construct adapters;
* construct repositories;
* construct services;
* select implementations from configuration;
* connect Ports to Adapters;
* construct workflows;
* construct application use cases;
* manage dependency lifetime where necessary.

The Composition Root must not:

* implement business rules;
* perform policy decisions;
* implement use cases;
* execute domain operations itself;
* perform workflow routing;
* contain model reasoning;
* become a general utility module.

Lower-level components must not import or query the Composition Root.

Dependency direction goes outward from the Composition Root into constructed components, never back toward it.

---

## Orchestration

Combining multiple capabilities into a single operation belongs to Application or Workflow orchestration.

For example:

```text
User Use Case
      ↓
Application
 ├─ Capability A
 ├─ Capability B
 ├─ Capability C
 └─ Domain / Policy
```

Individual capability modules remain independent.

The DI Container only assembles these components.

The Application or Workflow layer executes the actual use case.

Do not confuse dependency composition with business orchestration.

---

## Encapsulation

Treat module internals as private unless deliberately exposed as part of a contract.

Do not access another module's:

* private helpers;
* internal state;
* concrete repository implementation;
* provider-specific models;
* internal caches;
* private persistence details;

merely to avoid defining or using the correct boundary.

A leading private marker is not, however, sufficient evidence that an existing symbol can safely be removed or renamed.

Repository consumers must be checked first.

---

## Shared Code

Extract shared code only when the semantics are genuinely identical.

Do not generalize code merely because two implementations look similar.

If implementations share the same algorithm but require different domain-specific behavior, keep that difference explicit through parameters or narrow wrappers.

Prefer narrowly scoped support modules.

Avoid dumping grounds such as:

```text
utils
common
shared
helpers
misc
```

unless the contents genuinely share one cohesive responsibility.

If two pieces of code represent different business concepts, keep them separate even when their current implementation happens to be similar.

Duplication is preferable to a false abstraction.

---

## Structural Refactoring

Structural refactoring should improve responsibility ownership without changing observable behavior unless behavior change is explicitly requested.

Typical structural refactoring includes:

* moving cohesive behavior into its owning module;
* splitting a large component by responsibility;
* extracting shared deterministic helpers;
* replacing concrete cross-module dependencies with stable contracts;
* introducing explicit dependency injection;
* moving orchestration upward;
* reducing duplicated implementation;
* removing verified dead code.

For each structural refactor:

1. establish the behavioral baseline;
2. identify responsibility boundaries;
3. identify existing consumers;
4. extract one responsibility at a time;
5. preserve public and compatibility contracts;
6. inject dependencies explicitly;
7. remove obsolete dependency paths;
8. run focused tests after each meaningful extraction;
9. run broader regression tests before completion.

Do not combine broad behavior changes with broad structural refactoring in the same step unless explicitly required.

---

## Dead Code Removal

Do not classify code as dead solely because no production call site is immediately visible.

Before removing apparently unused code, inspect the repository for references across relevant surfaces, including:

* production source;
* tests;
* fixtures;
* prompt or model registries;
* evaluation artifacts;
* configuration;
* factories;
* plugin or extension boundaries;
* compatibility layers;
* migration or upgrade code when applicable.

"No active runtime caller found" does not prove that code is dead.

Code may intentionally exist as:

* a reserved capability;
* a compatibility surface;
* an experiment boundary;
* a registered contract;
* a test seam;
* a future-wired interface explicitly preserved by current design.

Only remove code when its ownership and references have been investigated sufficiently to show that it has no required role.

---

## Compatibility Surfaces

Internal-looking code can still form a repository-level compatibility surface.

Before moving, renaming, or deleting a symbol:

* search for repository consumers;
* inspect tests;
* inspect factories and registries;
* inspect dynamic lookup paths when applicable.

Do not assume that private naming means no consumer exists.

When an implementation should move but an existing consumer must remain supported, prefer a thin delegating compatibility wrapper rather than duplicating logic.

Compatibility wrappers should:

* remain small;
* contain no new business logic;
* delegate to the canonical implementation;
* be removed only when their consumers are intentionally migrated.

---

## Safety-Critical Boundaries

Operations that can change external state are safety-sensitive.

Safety-critical concerns include:

* authorization;
* user approval;
* argument integrity;
* execution authority;
* execution claims;
* external Write dispatch;
* idempotency;
* delivery uncertainty;
* verification;
* recovery;
* cancellation;
* command receipts;
* persistent safety audit.

Do not weaken these contracts for convenience or architectural cleanliness.

For structure-only refactoring of safety-critical code:

1. do not combine the extraction with behavior changes;
2. preserve call ordering;
3. preserve transaction boundaries;
4. preserve authorization and approval boundaries;
5. preserve argument integrity checks;
6. move one responsibility at a time;
7. run focused safety and contract tests after each extraction;
8. run the broader safety regression suite before completion.

If the requested task does not require changing a safety-critical boundary, prefer leaving it unchanged.

---

## External Effects

Treat every operation that can change an external system as an external effect.

Follow the canonical contracts for:

* authorization;
* approval;
* execution authority;
* argument integrity;
* idempotency;
* verification;
* recovery;
* cancellation.

Do not treat a successful external API response alone as proof that the intended product state is correct when verification is required.

When delivery outcome is uncertain:

* preserve uncertainty;
* do not blindly repeat the effect;
* follow the defined recovery path.

Never move external execution authority into prompts or model reasoning.

---

## State and Persistence

Treat Domain state and persistent data as authoritative according to their owning contracts.

Do not invent undocumented states or transitions.

Do not mutate persistent state from inappropriate layers.

Preserve:

* optimistic concurrency;
* command idempotency;
* transaction boundaries;
* persistent invariants.

Keep database transactions short.

Do not hold a write transaction open while waiting for:

* external APIs;
* model providers;
* remote tools;
* other long-running I/O.

Migration files are historical artifacts.

Do not rewrite previously applied migrations to represent a new change.

Create a new migration only when the current schema actually requires a new change.

---

## Workflow and Agent Behavior

Use models for responsibilities that require interpretation, synthesis, or reasoning.

Keep deterministic responsibilities in deterministic code.

Workflow and agent components must follow existing contracts rather than inventing new:

* routing semantics;
* memory semantics;
* tool semantics;
* persistent state;
* execution authority.

Agents should have narrow, cohesive responsibilities.

An agent or workflow component should receive only the state and dependencies required for its responsibility.

Prefer typed handoff contracts over implicit shared mutable state.

Do not allow agents to:

* bypass the Application boundary;
* bypass Domain or Policy;
* directly gain execution authority;
* treat model output as verification;
* create long-term memory unless explicitly defined;
* inject evaluation answers or hidden benchmark data into product prompts.

---

## Deterministic Safety

Model reasoning may propose or interpret.

Deterministic code must decide:

* whether an operation is allowed;
* whether approval is required;
* whether authorization is valid;
* whether state transition is legal;
* whether execution authority exists;
* whether execution arguments match the approved arguments;
* whether an external result is verified;
* whether recovery or retry is safe.

Do not move these decisions into prompts even if doing so appears to simplify implementation.

---

## Data and Secrets

Minimize exposure of sensitive information.

Never intentionally expose credentials, secrets, or unnecessary private user data through:

* source code;
* commits;
* logs;
* traces;
* test output;
* diagnostics;
* prompts;
* generated documentation.

Use fake, stub, synthetic, or isolated test infrastructure whenever possible.

Do not use live credentials or live user data for ordinary automated tests.

Do not perform destructive or externally visible live operations unless explicitly requested and allowed by the product safety contract.

---

## Frontend and Presentation

Presentation code is not authoritative for backend or domain facts.

When changing presentation code:

* inspect existing component and state patterns first;
* use documented API contracts;
* preserve backend ownership of domain state;
* keep visual-only changes separate from domain redesign unless the contract requires both;
* do not bypass application boundaries for convenience.

Client-side projections, caches, or progress displays must not become the source of truth for persistent business state.

---

## Testing

Use the repository's actual configured commands.

Do not guess command names or scripts.

Testing should be proportional to the change.

Run:

* focused tests for the changed behavior;
* relevant contract tests;
* relevant integration tests;
* broader regression tests appropriate to the risk.

If configured for the affected code, also run:

* lint;
* formatting checks;
* static type checking;
* builds;
* schema validation;
* other repository gates.

Do not claim completion while a relevant:

* safety test;
* state-transition test;
* interface test;
* regression test;

is failing.

---

## Refactoring Validation

For large structural refactoring, validate incrementally.

Do not perform a large extraction and wait until the end to test everything.

Preferred sequence:

```text
baseline
→ small extraction
→ focused tests
→ next extraction
→ focused tests
→ broader regression
```

When a refactor touches safety-critical code, increase the validation frequency.

A passing final test suite does not justify knowingly skipping intermediate validation of high-risk boundaries.

---

## Merge and Integration Validation

A conflict-free automatic merge does not prove semantic compatibility.

After integrating changes from another branch:

1. identify files modified by both sides;
2. inspect overlapping semantic areas even if no textual conflict occurred;
3. confirm that both intended changes remain present;
4. run focused tests for overlapping concerns;
5. run the appropriate broader regression suite.

Do not modify unrelated pre-existing failures merely because they become visible during integration.

Clearly distinguish:

* failures introduced by the current work;
* failures already present in the integration baseline.

---

## Repository Hygiene

Unless explicitly requested:

* do not commit;
* do not push;
* do not merge;
* do not rebase;
* do not switch branches;
* do not perform destructive Git operations.

Do not create unnecessary:

* changelogs;
* status files;
* handoff documents;
* scratch documents;
* temporary architecture reports.

Keep implementation artifacts inside the repository's established structure.

Do not commit generated or temporary files unless they are intentionally part of the repository contract.

---

## Investigation Before Questions

Investigate before asking the user for information that can be discovered from the repository.

Check:

* source code;
* tests;
* specifications;
* migrations;
* configuration;
* registries;
* existing patterns.

If a required contract remains missing or contradictory after investigation:

* identify the exact ambiguity;
* explain which concerns are affected;
* preserve the safer existing behavior;
* do not invent a contract.

If a true contract change is required, identify its impact before implementation.

---

## Completion Criteria

A coding task is complete only when:

* the requested concern is implemented;
* architectural boundaries remain valid;
* relevant compatibility surfaces are preserved or intentionally migrated;
* relevant tests pass;
* relevant static checks pass;
* safety-critical contracts remain intact;
* no unrelated change was introduced.

---

## Completion Report

At the end of a coding task, report concisely:

* what changed;
* which areas were affected;
* which important boundaries or contracts were preserved;
* tests and checks executed;
* their results;
* remaining manual or live verification;
* repository-versus-document mismatches discovered;
* pre-existing failures that were intentionally left untouched.

Do not create a separate report artifact unless explicitly requested.

---

## Core Engineering Principle

Prefer:

```text
high cohesion,
low coupling,
explicit dependencies,
clear ownership,
contract consistency,
deterministic safety,
recoverability,
minimal complete change,
and verifiable behavior
```

over:

```text
convenience,
implicit dependencies,
cross-module reach-through,
service-location,
false abstraction,
speculative redesign,
or shorter code.
```

The central rule is:

```text
Modules own capabilities.
Application and Workflow own orchestration.
Ports own boundaries.
Adapters own external implementations.
The Composition Root owns construction and wiring.
Domain and Policy own deterministic rules.
```

Keep those responsibilities separate.
