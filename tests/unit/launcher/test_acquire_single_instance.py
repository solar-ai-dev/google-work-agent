from launcher.acquire_single_instance import acquire_single_instance


def test_acquire_single_instance__has_exact__launcher_owner() -> None:
    assert acquire_single_instance.__module__ == "launcher.acquire_single_instance"
    assert acquire_single_instance.__name__ == "acquire_single_instance"
