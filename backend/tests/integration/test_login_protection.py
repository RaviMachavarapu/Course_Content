"""Login protection (spec docs/superpowers/specs/2026-10-29-login-protection.md).

Trusted-device cookie, growing per-email delays instead of a hard block, a
failures-only per-IP limit, the failed-sign-in alert mail, and the sign-up /
reset limits. Time comes from an injected fake clock.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.api.deps import get_clock
from app.auth import device, hashing, login, password_reset
from app.auth.cookies import set_device_cookie
from app.cli import seed_admin
from app.config import Settings, get_settings
from app.models.user import User

GOOD_PW = "sup3r-secret-pw"
BAD_PW = "wrong-pass-123"
STUDENT_LOGIN = "/api/student/auth/login"
ADMIN_LOGIN = "/api/admin/auth/login"
SECRET = "test-device-cookie-secret"


class FakeClock:
    def __init__(self, now: float = 1_800_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _settings(**over: Any) -> Settings:
    base: dict[str, Any] = {
        "login_rate_limit": "100/15m",
        "login_failure_window_sec": 900,
        "login_free_failures": 5,
        "login_device_free_failures": 10,
        "login_delay_base_sec": 2,
        "login_delay_max_sec": 60,
        "device_cookie_secret": SECRET,
        "device_cookie_max_age_days": 180,
        "register_rate_limit": "1000/1h",
        "password_reset_rate_limit": "1000/1h",
    }
    return Settings(**{**base, **over})


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def settings() -> Settings:
    return _settings()


@pytest.fixture
def app_client(client: TestClient, clock: FakeClock, settings: Settings) -> Iterator[TestClient]:
    client.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    client.app.dependency_overrides[get_clock] = lambda: clock  # type: ignore[attr-defined]
    yield client
    client.app.dependency_overrides.pop(get_settings, None)  # type: ignore[attr-defined]
    client.app.dependency_overrides.pop(get_clock, None)  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def mails(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    sent: list[dict[str, str]] = []

    def fake_send(_settings: Settings, *, to: str, subject: str, body: str) -> None:
        sent.append({"to": to, "subject": subject, "body": body})

    monkeypatch.setattr(login, "send_mail", fake_send)
    return sent


def _other(client: TestClient, ip: str) -> TestClient:
    """Another browser (no cookies) from another address, same app."""
    return TestClient(client.app, client=(ip, 50000))


def _register(client: TestClient, email: str) -> None:
    r = _other(client, "10.250.0.1").post(
        "/api/student/auth/register",
        json={"email": email, "password": GOOD_PW, "display_name": "S"},
    )
    assert r.status_code == status.HTTP_201_CREATED, r.text


def _login(client: TestClient, email: str, password: str = GOOD_PW, path: str = STUDENT_LOGIN):
    return client.post(path, json={"email": email, "password": password})


def _trusted_device(client: TestClient, email: str, ip: str = "10.1.0.1") -> TestClient:
    """A browser that has signed in once (holds the device cookie), signed out
    of its session again."""
    browser = _other(client, ip)
    assert _login(browser, email).status_code == status.HTTP_200_OK
    assert browser.cookies.get("sdp_device_student")
    browser.cookies.delete("sdp_student")
    return browser


def _lock_email(client: TestClient, email: str, ip: str = "10.66.0.1") -> TestClient:
    """An attacker makes 6 failures: the email is now delayed."""
    attacker = _other(client, ip)
    for _ in range(6):
        assert _login(attacker, email, BAD_PW).status_code == status.HTTP_401_UNAUTHORIZED
    assert _login(attacker, email, BAD_PW).status_code == status.HTTP_429_TOO_MANY_REQUESTS
    return attacker


@pytest.fixture
def fast_verify(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Memoise Argon2 in the login flow (for 100+ attempts); records each call
    so tests can see whether a password was checked."""
    calls: list[str] = []
    real = hashing.verify_password
    seen: dict[tuple[str, str], bool] = {}

    def spy(password_hash: str, password: str) -> bool:
        calls.append(password)
        if (password_hash, password) not in seen:
            seen[(password_hash, password)] = real(password_hash, password)
        return seen[(password_hash, password)]

    monkeypatch.setattr(login, "verify_password", spy)
    return calls


# ---------------------------------------------------------------- device cookie


def test_success_sets_the_device_cookie(app_client: TestClient, db_session: Session) -> None:
    _register(app_client, "dev@example.com")
    r = _login(app_client, "dev@example.com")
    assert r.status_code == status.HTTP_200_OK
    header = next(
        h for h in r.headers.get_list("set-cookie") if h.startswith("sdp_device_student=")
    )
    lowered = header.lower()
    assert "httponly" in lowered
    assert "samesite=lax" in lowered
    assert "path=/" in lowered
    assert f"max-age={180 * 86400}" in lowered
    assert "secure" not in lowered  # dev
    # the areas stay independent: a student login sets no admin device cookie
    assert not any(h.startswith("sdp_device_admin=") for h in r.headers.get_list("set-cookie"))

    seed_admin(db_session, email="boss@example.com", display_name="B", password="admin-pw-12345")
    db_session.flush()
    a = _login(_other(app_client, "10.5.0.1"), "boss@example.com", "admin-pw-12345", ADMIN_LOGIN)
    assert a.status_code == status.HTTP_200_OK
    names = [h.split("=", 1)[0] for h in a.headers.get_list("set-cookie")]
    assert "sdp_device_admin" in names
    assert "sdp_device_student" not in names


def test_device_cookie_is_secure_outside_dev() -> None:
    response = Response()
    set_device_cookie(response, "admin", "tok", Settings.model_construct(app_env="staging"))
    assert "secure" in response.headers["set-cookie"].lower()


def test_valid_device_cookie_bypasses_the_email_delay(app_client: TestClient) -> None:
    _register(app_client, "owner@example.com")
    laptop = _trusted_device(app_client, "owner@example.com")
    _lock_email(app_client, "owner@example.com")
    # the owner's own browser is not held up by the attacker's failures
    assert _login(laptop, "owner@example.com", BAD_PW).status_code == status.HTTP_401_UNAUTHORIZED
    assert _login(laptop, "owner@example.com").status_code == status.HTTP_200_OK


def _student(db: Session, email: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    assert user is not None
    return user


@pytest.mark.parametrize(
    "kind", ["valid", "forged", "expired", "other_user", "other_scope", "stale_stamp"]
)
def test_invalid_device_cookies_are_ignored(
    app_client: TestClient, db_session: Session, clock: FakeClock, settings: Settings, kind: str
) -> None:
    _register(app_client, "owner@example.com")
    _register(app_client, "someone@example.com")
    owner = _student(db_session, "owner@example.com")
    other = _student(db_session, "someone@example.com")

    def token(**over: Any) -> str:
        args: dict[str, Any] = {
            "user_id": str(owner.id),
            "scope": "student",
            "password_hash": owner.password_hash,
            "now": clock(),
        }
        args.update(over)
        return device.issue_device_token(settings, **args)

    if kind == "valid":  # control: a well-formed token for this account works
        value = token()
    elif kind == "forged":
        good = token()
        value = good[:-4] + ("AAAA" if not good.endswith("AAAA") else "BBBB")
    elif kind == "expired":
        value = token(now=clock() - 181 * 86400)
    elif kind == "other_user":
        value = token(user_id=str(other.id), password_hash=other.password_hash)
    elif kind == "other_scope":
        value = token(scope="admin")
    else:
        value = token(password_hash="$argon2id$old-password-hash")

    _lock_email(app_client, "owner@example.com")
    browser = _other(app_client, "10.1.0.9")
    browser.cookies.set("sdp_device_student", value)
    r = _login(browser, "owner@example.com")
    expected = status.HTTP_200_OK if kind == "valid" else status.HTTP_429_TOO_MANY_REQUESTS
    assert r.status_code == expected


def test_a_cookie_is_valid_until_it_expires(app_client: TestClient, clock: FakeClock) -> None:
    _register(app_client, "owner@example.com")
    laptop = _trusted_device(app_client, "owner@example.com")
    clock.advance(179 * 86400)
    _lock_email(app_client, "owner@example.com")
    assert _login(laptop, "owner@example.com").status_code == status.HTTP_200_OK


def test_a_password_reset_invalidates_device_cookies(
    app_client: TestClient, db_session: Session, redis_client: Any
) -> None:
    _register(app_client, "owner@example.com")
    laptop = _trusted_device(app_client, "owner@example.com")
    owner = _student(db_session, "owner@example.com")
    reset = password_reset.issue_reset_token(redis_client, user_id=owner.id, scope="student")
    new_pw = "brand-new-pass-456"
    r = _other(app_client, "10.7.0.1").post(
        "/api/student/auth/password-reset/confirm", json={"token": reset, "password": new_pw}
    )
    assert r.status_code == status.HTTP_204_NO_CONTENT
    _lock_email(app_client, "owner@example.com")
    assert _login(laptop, "owner@example.com", new_pw).status_code == (
        status.HTTP_429_TOO_MANY_REQUESTS
    )


def test_device_attempts_have_their_own_counter(
    app_client: TestClient, clock: FakeClock, fast_verify: list[str]
) -> None:
    """A stolen device cookie gets 10 free failures, then the same growing
    delays — for that device only."""
    _register(app_client, "owner@example.com")
    stolen = _trusted_device(app_client, "owner@example.com")
    for _ in range(11):
        assert _login(stolen, "owner@example.com", BAD_PW).status_code == (
            status.HTTP_401_UNAUTHORIZED
        )
    r = _login(stolen, "owner@example.com", BAD_PW)
    assert r.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert r.json()["error"]["retry_after"] == 2
    # the device's failures don't delay the email for everyone else
    assert _login(_other(app_client, "10.8.0.1"), "owner@example.com").status_code == (
        status.HTTP_200_OK
    )
    # nor do they reset the device's own counter (only its own success does)
    assert _login(stolen, "owner@example.com").status_code == status.HTTP_429_TOO_MANY_REQUESTS
    clock.advance(2)
    assert _login(stolen, "owner@example.com").status_code == status.HTTP_200_OK
    # success cleared the device's count: 10 free failures again
    for _ in range(10):
        assert _login(stolen, "owner@example.com", BAD_PW).status_code == (
            status.HTTP_401_UNAUTHORIZED
        )


# ------------------------------------------------------------- growing delays


def test_unit_delay_schedule() -> None:
    delays = [login.growing_delay(n, free=5, base=2, cap=60) for n in range(0, 14)]
    assert delays == [0, 0, 0, 0, 0, 0, 2, 4, 8, 16, 32, 60, 60, 60]


def test_delay_schedule_and_early_attempts(
    app_client: TestClient, clock: FakeClock, fast_verify: list[str]
) -> None:
    _register(app_client, "target@example.com")
    attacker = _other(app_client, "10.66.0.1")
    for _ in range(5):  # the first five failures: no delay
        assert _login(attacker, "target@example.com", BAD_PW).status_code == 401
    assert _login(attacker, "target@example.com", BAD_PW).status_code == 401  # 6th failure

    for expected in (2, 4, 8, 16, 32, 60, 60):
        checks = len(fast_verify)
        early = _login(attacker, "target@example.com", GOOD_PW)
        assert early.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert early.json()["error"]["code"] == "rate_limited"
        assert early.json()["error"]["retry_after"] == expected
        assert early.headers["Retry-After"] == str(expected)
        assert len(fast_verify) == checks  # rejected without checking the password
        clock.advance(expected - 1)
        partway = _login(attacker, "target@example.com", BAD_PW)
        assert partway.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert partway.json()["error"]["retry_after"] == 1
        clock.advance(1)
        # an early attempt didn't count: the next failure is the next step only
        assert _login(attacker, "target@example.com", BAD_PW).status_code == 401


def test_the_delay_applies_from_any_ip(app_client: TestClient, fast_verify: list[str]) -> None:
    _register(app_client, "target@example.com")
    for i in range(6):
        assert _login(_other(app_client, f"10.9.0.{i}"), "target@example.com", BAD_PW).status_code
    assert _login(_other(app_client, "10.9.1.1"), "target@example.com").status_code == 429


def test_unknown_emails_are_delayed_like_known_ones(
    app_client: TestClient, fast_verify: list[str]
) -> None:
    _register(app_client, "real@example.com")
    known = [_login(_other(app_client, "10.3.0.1"), "real@example.com", BAD_PW) for _ in range(7)]
    ghost = [_login(_other(app_client, "10.3.0.2"), "ghost@example.com", BAD_PW) for _ in range(7)]
    assert [r.status_code for r in known] == [r.status_code for r in ghost]
    assert [r.content for r in known] == [r.content for r in ghost]


def test_success_clears_the_email_count(app_client: TestClient, clock: FakeClock) -> None:
    _register(app_client, "forgetful@example.com")
    browser = _other(app_client, "10.4.0.1")
    for _ in range(6):
        _login(browser, "forgetful@example.com", BAD_PW)
    clock.advance(2)
    assert _login(browser, "forgetful@example.com").status_code == status.HTTP_200_OK
    browser.cookies.clear()  # also drop the device cookie
    codes = [_login(browser, "forgetful@example.com", BAD_PW).status_code for _ in range(6)]
    assert codes == [status.HTTP_401_UNAUTHORIZED] * 6


def test_failures_age_out_of_the_15_minute_window(
    app_client: TestClient, clock: FakeClock, fast_verify: list[str]
) -> None:
    _register(app_client, "target@example.com")
    _lock_email(app_client, "target@example.com")
    clock.advance(901)
    codes = [
        _login(_other(app_client, "10.6.0.1"), "target@example.com", BAD_PW).status_code
        for _ in range(6)
    ]
    assert codes == [status.HTTP_401_UNAUTHORIZED] * 6


def test_scopes_have_separate_email_counters(
    app_client: TestClient, db_session: Session, fast_verify: list[str]
) -> None:
    seed_admin(db_session, email="boss@example.com", display_name="B", password="admin-pw-12345")
    db_session.flush()
    for _ in range(7):
        _login(_other(app_client, "10.2.0.1"), "boss@example.com", BAD_PW)  # student area
    r = _login(_other(app_client, "10.2.0.2"), "boss@example.com", "admin-pw-12345", ADMIN_LOGIN)
    assert r.status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------- per IP


def test_ip_limit_counts_failures_only(
    app_client: TestClient, clock: FakeClock, fast_verify: list[str]
) -> None:
    _register(app_client, "class@example.com")
    school = _other(app_client, "10.20.0.1")
    assert _login(school, f"{uuid.uuid4().hex}@example.com", BAD_PW).status_code == 401
    clock.advance(10)
    for _ in range(98):
        assert _login(school, f"{uuid.uuid4().hex}@example.com", BAD_PW).status_code == 401
    # a whole class signing in from the same address never counts
    for _ in range(20):
        assert _login(school, "class@example.com").status_code == status.HTTP_200_OK
        school.cookies.clear()
    assert _login(school, f"{uuid.uuid4().hex}@example.com", BAD_PW).status_code == 401  # 100th
    r = _login(school, "class@example.com")
    assert r.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert r.json()["error"]["code"] == "rate_limited"
    assert r.json()["error"]["retry_after"] == 890  # until the oldest failure expires
    assert r.headers["Retry-After"] == "890"
    # other addresses are unaffected
    assert _login(_other(app_client, "10.21.0.1"), "class@example.com").status_code == 200
    clock.advance(890)
    assert _login(school, "class@example.com").status_code == status.HTTP_200_OK


def test_ip_limit_also_applies_to_device_cookie_attempts(
    app_client: TestClient, settings: Settings, fast_verify: list[str]
) -> None:
    _register(app_client, "owner@example.com")
    laptop = _trusted_device(app_client, "owner@example.com", ip="10.30.0.1")
    for _ in range(100):
        _login(laptop, f"{uuid.uuid4().hex}@example.com", BAD_PW)
    assert _login(laptop, "owner@example.com").status_code == status.HTTP_429_TOO_MANY_REQUESTS


# ----------------------------------------------------------------------- alert


def test_alert_mail_once_per_hour_at_five_failures(
    app_client: TestClient, clock: FakeClock, mails: list[dict[str, str]], fast_verify: list[str]
) -> None:
    _register(app_client, "owner@example.com")
    attacker = _other(app_client, "10.66.0.1")
    for _ in range(4):
        _login(attacker, "owner@example.com", BAD_PW)
    assert mails == []
    _login(attacker, "owner@example.com", BAD_PW)
    assert len(mails) == 1
    mail = mails[0]
    assert mail["to"] == "owner@example.com"
    assert mail["subject"] == "Several failed sign-ins to your account"
    assert "UTC" in mail["body"]
    assert "/forgot-password" in mail["body"]
    assert "10.66.0.1" not in mail["body"]
    # more failures within the hour: no more mail
    for _ in range(4):
        clock.advance(61)
        _login(attacker, "owner@example.com", BAD_PW)
    assert len(mails) == 1
    clock.advance(3600)
    _login(attacker, "owner@example.com", BAD_PW)
    assert len(mails) == 2


def test_alert_after_a_success_needs_five_new_failures(
    app_client: TestClient, clock: FakeClock, mails: list[dict[str, str]], fast_verify: list[str]
) -> None:
    _register(app_client, "owner@example.com")
    browser = _other(app_client, "10.40.0.1")
    for _ in range(4):
        _login(browser, "owner@example.com", BAD_PW)
    assert _login(browser, "owner@example.com").status_code == 200
    browser.cookies.clear()
    _login(browser, "owner@example.com", BAD_PW)
    assert mails == []  # not five consecutive


def test_no_alert_for_unknown_emails_or_device_attempts(
    app_client: TestClient, mails: list[dict[str, str]], fast_verify: list[str]
) -> None:
    for _ in range(6):
        _login(_other(app_client, "10.50.0.1"), "ghost@example.com", BAD_PW)
    _register(app_client, "owner@example.com")
    laptop = _trusted_device(app_client, "owner@example.com")
    for _ in range(8):
        _login(laptop, "owner@example.com", BAD_PW)
    assert mails == []


def test_admin_alert_links_the_admin_reset_page(
    app_client: TestClient, db_session: Session, mails: list[dict[str, str]], fast_verify: list[str]
) -> None:
    seed_admin(db_session, email="boss@example.com", display_name="B", password="admin-pw-12345")
    db_session.flush()
    for _ in range(5):
        _login(_other(app_client, "10.60.0.1"), "boss@example.com", BAD_PW, ADMIN_LOGIN)
    assert len(mails) == 1
    assert "/admin/forgot-password" in mails[0]["body"]


def test_alert_is_sent_off_the_request_path_and_reveals_nothing(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch, fast_verify: list[str]
) -> None:
    order: list[str] = []
    monkeypatch.setattr(login, "send_mail", lambda *_a, **_k: order.append("mail"))

    def boom(*_a: object, **_k: object) -> None:
        order.append("mail-failed")
        raise OSError("smtp down")

    from starlette.background import BackgroundTasks

    real_add = BackgroundTasks.add_task

    def spy(self: BackgroundTasks, func: Any, *a: Any, **k: Any) -> None:
        order.append("scheduled")
        real_add(self, func, *a, **k)

    monkeypatch.setattr(BackgroundTasks, "add_task", spy)
    _register(app_client, "owner@example.com")
    order.clear()
    known = [_login(_other(app_client, "10.70.0.1"), "owner@example.com", BAD_PW) for _ in range(5)]
    assert order == ["scheduled", "mail"]
    ghost = [_login(_other(app_client, "10.70.0.2"), "ghost@example.com", BAD_PW) for _ in range(5)]
    assert [r.content for r in known] == [r.content for r in ghost]
    assert [r.status_code for r in known] == [r.status_code for r in ghost]

    # SMTP down: still the same 401, never a 500
    monkeypatch.setattr(login, "send_mail", boom)
    _register(app_client, "second@example.com")
    codes = [
        _login(_other(app_client, "10.70.0.3"), "second@example.com", BAD_PW).status_code
        for _ in range(5)
    ]
    assert codes == [status.HTTP_401_UNAUTHORIZED] * 5
    assert "mail-failed" in order


# ------------------------------------------------------------ register / reset


def test_default_limits() -> None:
    fields = Settings.model_fields
    assert fields["login_rate_limit"].default == "100/15m"
    assert fields["register_rate_limit"].default == "100/1h"
    assert fields["password_reset_rate_limit"].default == "30/1h"
    assert fields["login_free_failures"].default == 5
    assert fields["login_device_free_failures"].default == 10
    assert fields["login_failure_window_sec"].default == 900
    assert fields["login_delay_base_sec"].default == 2
    assert fields["login_delay_max_sec"].default == 60
    assert fields["device_cookie_max_age_days"].default == 180
    assert password_reset.PER_EMAIL_REQUESTS_PER_HOUR == 3


def test_register_allows_100_per_hour_per_ip(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.student import auth as student_auth

    monkeypatch.setattr(student_auth, "hash_password", lambda _pw: "cheap-hash")
    settings = _settings(register_rate_limit=Settings.model_fields["register_rate_limit"].default)
    client.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    try:
        codes = []
        for i in range(101):
            codes.append(
                client.post(
                    "/api/student/auth/register",
                    json={
                        "email": f"pupil{i}@example.com",
                        "password": GOOD_PW,
                        "display_name": "P",
                    },
                ).status_code
            )
            client.cookies.clear()
        assert codes[:100] == [status.HTTP_201_CREATED] * 100
        assert codes[100] == status.HTTP_429_TOO_MANY_REQUESTS
    finally:
        client.app.dependency_overrides.pop(get_settings, None)  # type: ignore[attr-defined]


@pytest.mark.parametrize("area", ["student", "admin"])
def test_reset_request_allows_30_per_hour_per_ip(client: TestClient, area: str) -> None:
    settings = _settings(
        password_reset_rate_limit=Settings.model_fields["password_reset_rate_limit"].default
    )
    client.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    try:
        codes = [
            client.post(
                f"/api/{area}/auth/password-reset/request", json={"email": f"n{i}@example.com"}
            ).status_code
            for i in range(31)
        ]
        assert codes[:30] == [status.HTTP_202_ACCEPTED] * 30
        assert codes[30] == status.HTTP_429_TOO_MANY_REQUESTS
    finally:
        client.app.dependency_overrides.pop(get_settings, None)  # type: ignore[attr-defined]


def test_reset_mail_capped_at_3_per_hour_per_email_in_both_areas(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[str] = []
    monkeypatch.setattr(password_reset, "send_mail", lambda _s, *, to, **_k: sent.append(to))
    seed_admin(db_session, email="boss@example.com", display_name="B", password="admin-pw-12345")
    db_session.flush()
    for i in range(5):
        r = _other(client, f"10.80.0.{i}").post(
            "/api/admin/auth/password-reset/request", json={"email": "boss@example.com"}
        )
        assert r.status_code == status.HTTP_202_ACCEPTED
    assert sent == ["boss@example.com"] * 3
