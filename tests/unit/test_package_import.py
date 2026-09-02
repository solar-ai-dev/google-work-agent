import google_work_agent


def test_package_import__exposes__version() -> None:
    assert google_work_agent.__version__
