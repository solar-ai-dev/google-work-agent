from concurrent.futures import ThreadPoolExecutor

from google_work_agent.api.security.access_guard import LocalApiAccessGuard
from google_work_agent.api.security.bind import LocalBindPolicy
from google_work_agent.api.security.bootstrap import InMemoryBootstrapGrantStore
from google_work_agent.api.security.sessions import InMemoryLocalSessionManager
from google_work_agent.ports.system.api_access_port import (
    ApiRequestContext,
    EndpointPolicy,
)


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
    assert reused.detail_code == "BOOTSTRAP_REUSED"

    store.provision(secret="secret-2", service_instance_id="svc-1", now_ms=200)
    expired = store.consume(secret="secret-2", service_instance_id="svc-1", now_ms=211)
    assert expired.allowed is False
    assert expired.detail_code == "BOOTSTRAP_EXPIRED"


def test_local_session_manager_binds_service_instance() -> None:
    manager = InMemoryLocalSessionManager()
    token = manager.issue(service_instance_id="svc-1", now_ms=100)

    assert manager.resolve(token=token, service_instance_id="svc-1", now_ms=100) is not None
    assert manager.resolve(token=token, service_instance_id="svc-2", now_ms=100) is None
    assert manager.resolve(token=None, service_instance_id="svc-1", now_ms=100) is None


def test_local_session_manager_rejects_expired_and_revoked_sessions() -> None:
    manager = InMemoryLocalSessionManager(ttl_ms=10)
    expired = manager.issue(service_instance_id="svc-1", now_ms=100)
    assert manager.resolve(token=expired, service_instance_id="svc-1", now_ms=111) is None

    revoked = manager.issue(service_instance_id="svc-1", now_ms=200)
    manager.invalidate_all()
    assert manager.resolve(token=revoked, service_instance_id="svc-1", now_ms=201) is None


def test_bootstrap_failure_limit_expires_the_active_grant() -> None:
    store = InMemoryBootstrapGrantStore()
    store.provision(secret="valid", service_instance_id="svc-1", now_ms=100)

    for attempt in range(3):
        rejected = store.consume(
            secret=f"invalid-{attempt}",
            service_instance_id="svc-1",
            now_ms=101 + attempt,
        )
        assert rejected.allowed is False

    locked = store.consume(secret="valid", service_instance_id="svc-1", now_ms=105)
    assert locked.detail_code == "BOOTSTRAP_EXPIRED"


def test_bootstrap_consume_is_atomic_under_concurrency() -> None:
    store = InMemoryBootstrapGrantStore()
    store.provision(secret="valid", service_instance_id="svc-1", now_ms=100)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = tuple(
            executor.map(
                lambda _: store.consume(
                    secret="valid",
                    service_instance_id="svc-1",
                    now_ms=101,
                ),
                range(8),
            )
        )

    assert sum(result.allowed for result in results) == 1
    assert {result.detail_code for result in results if not result.allowed} == {"BOOTSTRAP_REUSED"}


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


def test_attachment_staging_is_the_only_multipart_mutation_exception() -> None:
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

    def authorize(path: str) -> bool:
        return guard.authorize(
            ApiRequestContext(
                method="POST",
                path=path,
                request_id="request-1",
                client_host="127.0.0.1",
                host="127.0.0.1:8765",
                origin="http://127.0.0.1:8765",
                content_type="multipart/form-data; boundary=bounded",
                session_token=session_token,
                sec_fetch_site="same-origin",
                sec_fetch_mode="cors",
                sec_fetch_dest="empty",
            ),
            endpoint_policy=EndpointPolicy.API_SESSION_REQUIRED,
        ).allowed

    assert authorize("/api/v1/attachments/stage") is True
    assert authorize("/api/v1/conversations") is False
