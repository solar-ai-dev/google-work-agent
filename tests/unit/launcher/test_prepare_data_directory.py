from launcher.prepare_data_directory import prepare_data_directory


def test_prepare_data_directory__has_exact__launcher_owner() -> None:
    assert prepare_data_directory.__module__ == "launcher.prepare_data_directory"
    assert prepare_data_directory.__name__ == "prepare_data_directory"
