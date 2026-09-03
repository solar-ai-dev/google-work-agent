from launcher.shutdown_service import shutdown_service


def test_shutdown_service__has_exact__launcher_owner() -> None:
    assert shutdown_service.__module__ == "launcher.shutdown_service"
    assert shutdown_service.__name__ == "shutdown_service"
