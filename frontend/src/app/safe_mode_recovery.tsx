type Props = {
  reason: string;
};

export function SafeModeRecovery({ reason }: Props): JSX.Element {
  return (
    <main className="startup">
      <section className="startup-card" aria-label="시작 차단 상태">
        <h1>앱을 시작할 수 없습니다</h1>
        <p role="status">
          시스템의 자동 복구가 완료되지 않아 데이터를 보존하고 실행을 중단했습니다.
        </p>
        <p className="status-warn">오류 코드: {reason}</p>
        <p>새 Run과 Write는 차단되어 있으며 기존 데이터는 변경하지 않았습니다.</p>
      </section>
    </main>
  );
}
