# 00. Authority · Read Order

**Normative detail of the current Repository Architecture Source.**

Read order:

1. Spec-to-code mapping
2. Directory ownership
3. Naming grammar
4. Artifact taxonomy
5. Dependency/import/export rules
6. LangGraph/state ownership
7. Connector/API/Persistence grammar
8. Single-authority/compat policy
9. Test/fixture/migration grammar
10. Error/event/config naming
11. Refactor playbook
12. Enforcement
13. Exception registry

Behavior remains owned by the applicable concern sources in 01–15 together with the Domain State Transition Contract and `04 Domain·DB` required persistence invariants where those concerns apply. The State Transition Test Matrix is normative verification authority for those contracts and implementation migrations do not independently define lifecycle behavior. If this detail conflicts with the current Repository Architecture Source page, the Source page wins.
