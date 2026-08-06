import google_work_agent


def test_package_import_exposes_version() -> None:
    assert google_work_agent.__version__
