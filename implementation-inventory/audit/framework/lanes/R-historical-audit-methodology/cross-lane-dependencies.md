# Cross-Lane Dependencies

- A~L worker output을 읽거나 수정하지 않는다.
- Coordinator에게 schema/automation/blind-spot recommendation만 handoff한다.
- X3/X4는 Coordinator가 채택·freeze한 방법론만 소비하며 historical row를 직접 소비하지 않는다.
