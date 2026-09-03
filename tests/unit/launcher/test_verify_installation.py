from launcher.verify_installation import verify_installation


def test_verify_installation__has_exact__launcher_owner() -> None:
    assert verify_installation.__module__ == "launcher.verify_installation"
    assert verify_installation.__name__ == "verify_installation"
