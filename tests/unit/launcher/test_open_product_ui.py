from launcher.open_product_ui import open_product_ui


def test_open_product_ui__has_exact__launcher_owner() -> None:
    assert open_product_ui.__module__ == "launcher.open_product_ui"
    assert open_product_ui.__name__ == "open_product_ui"
