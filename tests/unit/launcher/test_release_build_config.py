from launcher.release_build_config import SignedBuildConfigV1, load_signed_build_config


def test_release_build_config__has_exact__launcher_owner() -> None:
    assert SignedBuildConfigV1.__module__ == "launcher.release_build_config"
    assert load_signed_build_config.__module__ == "launcher.release_build_config"
