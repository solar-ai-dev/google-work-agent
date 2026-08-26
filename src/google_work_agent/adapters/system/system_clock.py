"""System clock adapter."""

import time


class SystemClockAdapter:
    def now_ms(self) -> int:
        return time.time_ns() // 1_000_000
