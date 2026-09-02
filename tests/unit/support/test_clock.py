from tests.support.fakes import FakeClockPort


def test_fake_clock__returns_same__initial_value() -> None:
    clock = FakeClockPort(initial_ms=100)

    assert clock.now_ms() == 100
    assert clock.now_ms() == 100


def test_fake_clock__advance_and__set_are_explicit() -> None:
    clock = FakeClockPort(initial_ms=10)

    assert clock.advance_ms(5) == 15
    assert clock.set_ms(99) == 99
    assert clock.now_ms() == 99


def test_fake_clock__rejects_negative__values() -> None:
    clock = FakeClockPort()

    try:
        clock.advance_ms(-1)
    except ValueError as error:
        assert "non-negative" in str(error)
    else:
        raise AssertionError("expected ValueError for negative advance")

    try:
        clock.set_ms(-1)
    except ValueError as error:
        assert "non-negative" in str(error)
    else:
        raise AssertionError("expected ValueError for negative set")
