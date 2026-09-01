# Google Work Agent Documentation

This `/docs` tree is optimized for coding and review agents.

## Start here

1. Read [`canonical/00-project-source-guide.md`](canonical/00-project-source-guide.md).
2. Follow the concern authority and dependency-safe read order declared there.
3. For exact production path/file/symbol ownership, read [`canonical/16-repository-architecture/16-repository-architecture-source.md`](canonical/16-repository-architecture/16-repository-architecture-source.md) and the relevant subordinate page.
4. Treat [`database/migrations/`](database/migrations/) as executable implementation artifacts, not independent behavioral authority.

## Directory roles

- `canonical/` — current Architecture-27 design authority used for implementation decisions.
- `canonical/16-repository-architecture/` — exact repository placement, naming, import/export, single-authority, and enforcement mapping.
- `database/migrations/` — byte-level mirror of executable production migrations present in the supplied repository baseline.

Historical `design/`, `contracts/`, `export/`, and the old functional coverage mapping are intentionally absent. Do not recover authority from those old paths or from git history when current canonical documents answer the question.

Architecture-27 also contains non-canonical rationale/archive material in its publication snapshot. Those pages are intentionally omitted from this GitHub coding-agent surface; they must not override `canonical/`.

## Fast routing by question

| Question | Read first |
| --- | --- |
| Product scope / feature behavior | `01`, `01-A`, `01-B` |
| UI behavior | `02` |
| Layer/system boundary | `03` |
| Domain facts / persistence invariant | `04` |
| Lifecycle command / transition | `04-A` |
| Retrieval | `05` |
| Agent / Workflow | `06` |
| API / Port / MCP | `07` |
| End-to-end sequence | `08` |
| Security / Auth | `09` |
| Runtime / deployment | `10` |
| Logging / audit | `11` |
| Test / state-transition oracle | `12`, `12-A` |
| Evaluation | `13` |
| Operations | `14` |
| Prompt / failure | `15` |
| Production path / file / symbol | `16 Repository Architecture` |

## Migration mirror rule

The undeployed Product uses one fresh-install schema, `0001_current_schema.sql`. The documentation mirror is byte-identical to the production artifact; historical upgrade sources remain in Git history. See [`database/README.md`](database/README.md).
