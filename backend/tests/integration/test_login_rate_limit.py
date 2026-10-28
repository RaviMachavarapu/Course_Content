"""Login rate limiting counts failures only (review 2026-10-28).

The limiter keys on the real client IP (`request.client.host`, which uvicorn's
proxy-headers support fills in from the trusted proxy's X-Forwarded-For) and on
the email. Successful logins never use up the budget, and a success clears the
email's failure count.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth import hashing
from app.cli import seed_admin
from app.config import Settings, get_settings

GOOD_PW = "sup3r-secret-pw"


@pytest.fixture
def limited(client: TestClient) -> Iterator[TestClient]:
    settings = Settings(login_rate_limit="3/5m")
    client.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    yield client
    client.app.dependency_overrides.pop(get_settings, None)  # type: ignore[attr-defined]


def _register(client: TestClient, email: str) -> None:
    r = client.post(
        "/api/student/auth/register",
        json={"email": email, "password": GOOD_PW, "display_name": "S"},
    )
    assert r.status_code == status.HTTP_201_CREATED
    client.cookies.clear()


def _login(client: TestClient, email: str, password: str = GOOD_PW) -> int:
    return client.post(
        "/api/student/auth/login", json={"email": email, "password": password}
    ).status_code


def test_successful_logins_do_not_use_up_the_budget(limited: TestClient) -> None:
    for i in range(6):
        _register(limited, f"class{i}@example.com")
    # a whole class logging in from one IP (well past the limit of 3)
    for i in range(6):
        assert _login(limited, f"class{i}@example.com") == status.HTTP_200_OK
        limited.cookies.clear()


def test_failures_are_limited_per_ip(limited: TestClient) -> None:
    codes = [_login(limited, f"nobody{i}@example.com", "wrong-pass") for i in range(5)]
    assert codes[:3] == [status.HTTP_401_UNAUTHORIZED] * 3
    assert codes[3] == status.HTTP_429_TOO_MANY_REQUESTS
    assert (
        limited.post(
            "/api/student/auth/login", json={"email": "x@example.com", "password": "y"}
        ).json()["error"]["code"]
        == "rate_limited"
    )


def test_failures_are_limited_per_email_across_ips(limited: TestClient) -> None:
    _register(limited, "target@example.com")
    for i in range(3):
        other = TestClient(limited.app, client=(f"10.0.0.{i}", 50000))
        assert _login(other, "target@example.com", "wrong-pass") == status.HTTP_401_UNAUTHORIZED
    assert _login(limited, "target@example.com", "wrong-pass") == (
        status.HTTP_429_TOO_MANY_REQUESTS
    )


def test_one_ip_failing_does_not_lock_out_other_ips(limited: TestClient) -> None:
    _register(limited, "real@example.com")
    for i in range(4):
        _login(limited, f"nobody{i}@example.com", "wrong-pass")
    other = TestClient(limited.app, client=("10.9.9.9", 50000))
    assert _login(other, "real@example.com") == status.HTTP_200_OK


def test_success_clears_the_email_failure_count(limited: TestClient) -> None:
    _register(limited, "forgetful@example.com")
    assert _login(limited, "forgetful@example.com", "typo-pass") == status.HTTP_401_UNAUTHORIZED
    assert _login(limited, "forgetful@example.com", "typo-pass") == status.HTTP_401_UNAUTHORIZED
    assert _login(limited, "forgetful@example.com") == status.HTTP_200_OK
    limited.cookies.clear()
    # the email bucket starts over: two more typos (from another device, so the
    # first IP's failures don't interfere) still don't lock the account
    phone = TestClient(limited.app, client=("10.1.1.1", 50000))
    assert _login(phone, "forgetful@example.com", "typo-pass") == status.HTTP_401_UNAUTHORIZED
    assert _login(phone, "forgetful@example.com", "typo-pass") == status.HTTP_401_UNAUTHORIZED
    assert _login(phone, "forgetful@example.com") == status.HTTP_200_OK


def test_scopes_have_separate_buckets(limited: TestClient, db_session: Session) -> None:
    seed_admin(db_session, email="boss@example.com", display_name="B", password="admin-pw-12345")
    db_session.flush()
    for _ in range(4):
        _login(limited, "someone@example.com", "wrong-pass")
    r = limited.post(
        "/api/admin/auth/login", json={"email": "boss@example.com", "password": "admin-pw-12345"}
    )
    assert r.status_code == status.HTTP_200_OK


def test_unknown_email_still_runs_a_password_hash(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No timing tell between "no such account" and "wrong password"."""
    calls: list[str] = []
    real = hashing.verify_password

    def spy(password_hash: str, password: str) -> bool:
        calls.append(password_hash)
        return real(password_hash, password)

    monkeypatch.setattr("app.auth.login.verify_password", spy)
    assert _login(client, "ghost@example.com", "whatever-1") == status.HTTP_401_UNAUTHORIZED
    assert len(calls) == 1


def test_forwarded_client_ips_get_separate_buckets(client: TestClient) -> None:
    """Behind nginx, uvicorn's proxy-headers middleware (trusting only the web
    container) turns X-Forwarded-For into `request.client`; the limiter must
    key on that, so two students behind the same proxy don't share a bucket."""
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    app = client.app
    settings = Settings(login_rate_limit="3/5m")
    app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    try:
        proxied = TestClient(
            ProxyHeadersMiddleware(app, trusted_hosts=["10.213.53.2"]),  # type: ignore[arg-type]
            client=("10.213.53.2", 50000),
        )

        def attempt(ip: str) -> int:
            return proxied.post(
                "/api/student/auth/login",
                json={"email": f"x-{ip}@example.com", "password": "wrong-pass"},
                headers={"X-Forwarded-For": ip},
            ).status_code

        assert [attempt("203.0.113.7") for _ in range(4)][-1] == (status.HTTP_429_TOO_MANY_REQUESTS)
        assert attempt("198.51.100.9") == status.HTTP_401_UNAUTHORIZED
    finally:
        app.dependency_overrides.pop(get_settings, None)  # type: ignore[attr-defined]
