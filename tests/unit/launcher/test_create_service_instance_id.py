from launcher.create_service_instance_id import create_service_instance_id


def test_create_service_instance_id__has_exact__launcher_owner() -> None:
    assert create_service_instance_id.__module__ == "launcher.create_service_instance_id"
    assert create_service_instance_id.__name__ == "create_service_instance_id"
