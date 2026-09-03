from launcher.allocate_dynamic_port import allocate_dynamic_port


def test_allocate_dynamic_port__has_exact__launcher_owner() -> None:
    assert allocate_dynamic_port.__module__ == "launcher.allocate_dynamic_port"
    assert allocate_dynamic_port.__name__ == "allocate_dynamic_port"
