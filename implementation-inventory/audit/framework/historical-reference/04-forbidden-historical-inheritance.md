# Forbidden Historical Inheritance

다음 historical 값은 current evidence로 상속 금지다.

- PASS, CLEAN, completion verdict
- row count와 coverage percentage
- finding와 disposition
- path, symbol, caller, import/export, runtime binding
- test와 fixture 존재/통과 상태
- package split, owner, registry, state writer 판정
- negative search result와 exception 목록

방법론을 채택하려면 current framework contract로 다시 명시하고, 실제 run에서는 `AUDIT_SHA`에서 evidence를 새로 수집해야 한다.
