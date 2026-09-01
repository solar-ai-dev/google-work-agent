# Cross-Lane Dependencies

읽기 전용 input은 Coordinator-frozen A~H manifest다. 발견한 semantic ambiguity는 원 owner lane ID에 handoff하고 worker가 owner row를 수정하지 않는다. X2~X4와는 Coordinator merge 전까지 직접 의존하지 않는다.
