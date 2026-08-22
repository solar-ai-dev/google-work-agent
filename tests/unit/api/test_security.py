from google_work_agent.api.security.access_guard import LocalApiAccessGuard
from google_work_agent.api.security.bind import LocalBindPolicy
from google_work_agent.api.security.bootstrap import InMemoryBootstrapGrantStore
from google_work_agent.api.security.sessions import InMemoryLocalSessionManager
from google_work_agent.ports import ApiRequestContext, EndpointPolicy


def test_local_bind_policy_requires_exact_ipv4_loopback() -> None:
    LocalBindPolicy(host="127.0.0.1", port=8765).validate()

    for host in ("localhost", "0.0.0.0", "192.168.0.10", "::1"):
        try:
            LocalBindPolicy(host=host, port=8765).validate()
        except ValueError:
            continue
        raise AssertionError(f"{host} should be rejected")


def test_bootstrap_grant_is_one_time_and_ttl_bound() -> None:
    store = InMemoryBootstrapGrantStore(ttl_ms=10)
    store.provision(secret="secret-1", service_instance_id="svc-1", now_ms=100)

    accepted = store.consume(secret="secret-1", service_instance_id="svc-1", now_ms=105)
    reused = store.consume(secret="secret-1", service_instance_id="svc-1", now_ms=106)

    assert accepted.allowed is True
    assert reused.allowed is False
    assert reused.detail_code == "BOOTSTRAP_SECRET_CONSUMED"

    store.provision(secret="secret-2", service_instance_id="svc-1", now_ms=200)
    expired = store.consume(secret="secret-2", service_instance_id="svc-1", now_ms=211)
    assert expired.allowed is False
    assert expired.detail_code == "BOOTSTRAP_SECRET_EXPIRED"


def test_local_session_manager_binds_service_instance() -> None:
    manager = InMemoryLocalSessionManager()
    token = manager.issue(service_instance_id="svc-1", now_ms=100)

    assert manager.validate(token=token, service_instance_id="svc-1") is True
    assert manager.validate(token=token, service_instance_id="svc-2") is False
    assert manager.validate(token=None, service_instance_id="svc-1") is False


def test_local_api_access_guard_enforces_origin_fetch_metadata_and_session() -> None:
    manager = InMemoryLocalSessionManager()
    session_token = manager.issue(service_instance_id="svc-1", now_ms=100)
    guard = LocalApiAccessGuard(
        expected_host="127.0.0.1:8765",
        expected_origin="http://127.0.0.1:8765",
        service_instance_id="svc-1",
        session_manager=manager,
        release_version="test",
        environment="test",
        now_ms=lambda: 100,
    )

    bootstrap_allowed = guard.authorize(
        ApiRequestContext(
            method="POST",
            path="/api/v1/session/bootstrap",
            request_id="req-1",
            client_host="127.0.0.1",
            host="127.0.0.1:8765",
            origin="http://127.0.0.1:8765",
            content_type="application/json; charset=utf-8",
            sec_fetch_site="same-origin",
            sec_fetch_mode="cors",
            sec_fetch_dest="empty",
        ),
        endpoint_policy=EndpointPolicy.BOOTSTRAP_EXCHANGE,
    )
    denied = guard.authorize(
        ApiRequestContext(
            method="POST",
            path="/api/v1/conversations",
            request_id="req-2",
            client_host="127.0.0.1",
            host="127.0.0.1:8765",
            origin="http://evil.example",
            content_type="application/json",
            session_token=session_token,
            sec_fetch_site="cross-site",
            sec_fetch_mode="cors",
            sec_fetch_dest="empty",
        ),
        endpoint_policy=EndpointPolicy.API_SESSION_REQUIRED,
    )
    allowed = guard.authorize(
        ApiRequestContext(
            method="GET",
            path="/api/v1/runtime",
            request_id="req-3",
            client_host="127.0.0.1",
            host="127.0.0.1:8765",
            origin="http://127.0.0.1:8765",
            content_type=None,
            session_token=session_token,
            sec_fetch_site="same-origin",
            sec_fetch_mode="cors",
            sec_fetch_dest="empty",
        ),
        endpoint_policy=EndpointPolicy.API_SESSION_REQUIRED,
    )

    assert bootstrap_allowed.allowed is True
    assert denied.allowed is False
    assert denied.detail_code == "ORIGIN_REQUIRED"
    assert allowed.allowed is True
