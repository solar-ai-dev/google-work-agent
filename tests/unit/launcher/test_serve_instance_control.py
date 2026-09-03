from launcher.serve_instance_control import serve_instance_control


def test_serve_instance_control__has_exact__launcher_owner() -> None:
    assert serve_instance_control.__module__ == "launcher.serve_instance_control"
    assert serve_instance_control.__name__ == "serve_instance_control"
