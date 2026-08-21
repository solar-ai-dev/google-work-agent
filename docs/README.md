# Google Work Agent Documentation Router

> **Navigation only — not a normative authority.**
>
> Every implementation, refactor, audit, or design task MUST begin with [`design/00-PROJECT-SOURCE-GUIDE.md`](design/00-PROJECT-SOURCE-GUIDE.md). The Source Guide resolves current canonical authority, versions, and Project Source inventory. If this router conflicts with the Source Guide, the Source Guide wins.

## Agent entry rule

1. Read `design/00-PROJECT-SOURCE-GUIDE.md` first.
2. Identify the concern you are changing or auditing.
3. Read the canonical owner document for that concern.
4. Read any executable/supporting contract named below before changing behavior.
5. For repository placement, filenames, symbols, imports/exports, or structural refactoring, additionally read `design/16-repository-architecture-source.md` and only the relevant subordinate detail under `design/16-repository-architecture/`.
6. Never treat `export/` artifacts, change history, current code placement, or an older filename version as higher authority than the Source Guide and concern owner.

## Concern → canonical owner

| Concern | Read first | Also read when relevant |
|---|---|---|
| Product goals / scope | `design/01-requirements-prd.md` | Functional, Policy |
| User-visible functional behavior | `design/01-a-functional-definition.md` | PRD, Policy, UI/UX |
| Safety / approval / prohibition | `design/01-b-policy-definition-v2.8.md` | Domain state contract, Interface, Security |
| UI / interaction | `design/02-ui-ux-design.md` | Functional, Sequence |
| System / layer boundaries | `design/03-system-architecture.md` | Repository Architecture for repository enforcement |
| Domain facts / state transitions / DB invariants | `design/04-domain-database-design.md` | `contracts/state-transition-contract-v1.4.md`, `database/migrations/` |
| Retrieval / evidence | `design/05-context-retrieval.md` | Workflow, Interface, Test |
| Agents / Main Graph / Subgraphs / State / Node / Edge | `design/06-agent-workflow.md` | Prompt Contract, Sequence, Test, Repository Architecture |
| Tool / MCP / internal interfaces | `design/07-tool-mcp-internal-interface.md` | Architecture, Policy, Security |
| End-to-end interaction order | `design/08-sequence-design.md` | Workflow, Domain, Interface |
| Security / Auth | `design/09-security-auth-v2.5.md` | Policy, Interface, Infrastructure |
| Infrastructure / environment | `design/10-infrastructure-environment-v2.7.md` | Architecture, Security |
| Observability / trace / audit | `design/11-observability-logging-audit.md` | Workflow, Interface, Prompt Contract |
| Product regression verification | `design/12-test-design.md` | All product contracts being tested |
| Candidate comparison / experiments | `design/13-evaluation-experiment.md` | Workflow, Prompt Contract, Retrieval |
| Operations / troubleshooting | `design/14-operations-troubleshooting.md` | Domain, Interface, Security |
| Prompt / failure / evaluation-normalized Agent contract | `design/15-agent-capability-failure-prompt-contract.md` | Workflow, Retrieval, Test, Evaluation |
| Repository placement / naming / imports / single production authority | `design/16-repository-architecture-source.md` | Relevant `design/16-repository-architecture/*` detail |

## Directory meaning

```text
docs/
├── README.md                    # this non-normative navigation router
├── design/                      # canonical design/source documents
│   ├── 00-PROJECT-SOURCE-GUIDE.md  # mandatory authority resolver
│   └── 16-repository-architecture/  # subordinate normative repository detail
├── contracts/                   # explicit domain/state contracts; filename may preserve historical compatibility
├── database/migrations/         # immutable executable DB history/constraints
└── export/                      # snapshots, manifests, changelogs, history; never authority by itself
```

## Fast routes for implementation agents

**Changing behavior:** Source Guide → semantic concern owner → dependent Domain/Policy/Interface contract → Test.

**Changing Agent workflow:** Source Guide → `06` → `15` → `08` → `12`/`13`; add `16` when files/modules/ownership change.

**Changing persistence or state transitions:** Source Guide → `04` → state transition contract → every applied migration affecting the invariant → `12`.

**Structural refactor / naming only:** Source Guide → `16` → relevant subordinate `16/*` document → semantic owner document; behavior must remain unchanged unless that owner explicitly versions a behavior change.

**Auditing current authority:** Source Guide first. `export/` is evidence/history only and must not be used to override current canonical sources.
