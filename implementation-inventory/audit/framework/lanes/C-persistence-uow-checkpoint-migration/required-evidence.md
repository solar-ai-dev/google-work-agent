# Required Evidence

- Port → repository/adapter → schema/table/index/constraint trace
- UoW begin/commit/rollback 및 external I/O 경계
- migration discovery/order/checksum/current schema evidence
- checkpoint writer/reader와 Domain Store truth 분리
- B invariant와 D/F consumer를 secondary link로 기록
