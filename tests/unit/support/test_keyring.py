from tests.support.fakes import FakeKeyring


def test_fake_keyring_supports_set_get_delete() -> None:
    keyring = FakeKeyring()

    assert keyring.get_secret(service="gmail", account="user-1") is None
    keyring.set_secret(service="gmail", account="user-1", secret="token-1")
    assert keyring.get_secret(service="gmail", account="user-1") == "token-1"
    assert keyring.delete_secret(service="gmail", account="user-1") is True
    assert keyring.get_secret(service="gmail", account="user-1") is None
    assert keyring.delete_secret(service="gmail", account="user-1") is False


def test_fake_keyring_isolates_service_and_account_and_redacts_repr() -> None:
    keyring = FakeKeyring()
    keyring.set_secret(service="gmail", account="user-1", secret="secret-a")
    keyring.set_secret(service="calendar", account="user-1", secret="secret-b")
    keyring.set_secret(service="gmail", account="user-2", secret="secret-c")

    assert keyring.get_secret(service="gmail", account="user-1") == "secret-a"
    assert keyring.get_secret(service="calendar", account="user-1") == "secret-b"
    assert keyring.get_secret(service="gmail", account="user-2") == "secret-c"
    assert "secret-a" not in repr(keyring)
    assert "secret-b" not in repr(keyring)
    assert "secret-c" not in repr(keyring)
