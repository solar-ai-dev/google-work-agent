from launcher.request_existing_instance_ui import request_existing_instance_ui


def test_request_existing_instance_ui__has_exact__launcher_owner() -> None:
    assert request_existing_instance_ui.__module__ == "launcher.request_existing_instance_ui"
    assert request_existing_instance_ui.__name__ == "request_existing_instance_ui"
