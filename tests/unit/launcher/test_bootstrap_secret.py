import base64

from launcher.bootstrap_secret import create_bootstrap_secret


def test_create_bootstrap_secret_is_unique_and_has_at_least_256_bits() -> None:
    first = create_bootstrap_secret()
    second = create_bootstrap_secret()

    assert first != second
    decoded = base64.urlsafe_b64decode(first + "=" * (-len(first) % 4))
    assert len(decoded) >= 32
