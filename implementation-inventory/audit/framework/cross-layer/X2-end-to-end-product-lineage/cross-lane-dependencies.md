# Cross-Lane Dependencies

Coordinator-frozen A~K input만 읽는다. X1~X4는 병렬 독립이며 결과 상호 참조는 Coordinator merge 후 생성한다. missing lane evidence는 unchecked/handoff로 남긴다.
