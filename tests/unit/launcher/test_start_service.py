from launcher.start_service import start_service


def test_start_service__has_exact__launcher_owner() -> None:
    assert start_service.__module__ == "launcher.start_service"
    assert start_service.__name__ == "start_service"
