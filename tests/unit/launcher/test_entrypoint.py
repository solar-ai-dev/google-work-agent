from launcher.entrypoint import main


def test_entrypoint__has_exact__launcher_owner() -> None:
    assert main.__module__ == "launcher.entrypoint"
    assert main.__name__ == "main"
