# Authority Manifest

모든 worker는 `docs/canonical/00-project-source-guide.md`의 concern authority와 dependency-safe read order를 우선한다.

## Canonical design sources — exactly 21

1. `docs/canonical/00-project-source-guide.md`
2. `docs/canonical/01-requirements-prd.md`
3. `docs/canonical/01-a-functional-definition.md`
4. `docs/canonical/01-b-policy-definition.md`
5. `docs/canonical/02-ui-ux-design.md`
6. `docs/canonical/03-system-architecture.md`
7. `docs/canonical/04-domain-database-design.md`
8. `docs/canonical/05-context-retrieval.md`
9. `docs/canonical/06-agent-workflow.md`
10. `docs/canonical/07-tool-mcp-internal-interface.md`
11. `docs/canonical/08-sequence-design.md`
12. `docs/canonical/09-security-auth.md`
13. `docs/canonical/10-infrastructure-environment.md`
14. `docs/canonical/11-observability-logging-audit.md`
15. `docs/canonical/12-test-design.md`
16. `docs/canonical/13-evaluation-experiment.md`
17. `docs/canonical/14-operations-troubleshooting.md`
18. `docs/canonical/15-agent-capability-failure-prompt-contract.md`
19. `docs/canonical/16-repository-architecture/16-repository-architecture-source.md`
20. `docs/canonical/04-a-domain-state-transition-contract.md`
21. `docs/canonical/12-a-state-transition-test-matrix.md`

## Repository Architecture subordinate order

`docs/canonical/16-repository-architecture/00-authority-read-order.md` 다음에 `01`부터 `13`까지 숫자 순서로 읽는다. Subordinate 문서는 16 Source의 normative detail이며 별도 design-source count를 만들지 않는다.

Executable migration과 test/evaluation artifact는 구현·검증 자료이지 독립 behavior authority가 아니다.
