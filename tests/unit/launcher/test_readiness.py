from launcher.readiness import wait_for_service_ready


def test_readiness__has_exact__launcher_owner() -> None:
    assert wait_for_service_ready.__module__ == "launcher.readiness"
    assert wait_for_service_ready.__name__ == "wait_for_service_ready"
