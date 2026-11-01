# ruff: noqa: F811  (the fixtures are imported from test_login_protection)
"""Login protection, owner decisions of 2026-10-29 (spec amendment in
docs/superpowers/specs/2026-10-29-login-protection.md) and review findings:

- "Remember this device": the device cookie is set only when asked for; logging
  out of a session that wasn't remembered leaves no device cookie behind.
- Wrong guesses carrying a device cookie also count toward the alert mail.
- Completing a password reset makes that browser a trusted device.
- A trusted-device success doesn't clear an attacker's per-email backoff.
- One alert mail per burst, even for concurrent failures.
- Signing in destroys the session the browser already had.
"""

from __future__ import annotations

from typing import Any

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth import password_reset
from tests.integration.test_login_protection import (  # noqa: F401  (fixtures)
    BAD_PW,
    GOOD_PW,
    STUDENT_LOGIN,
    FakeClock,
    _burst,
    _lock_email,
    _login,
    _other,
    _register,
    _student,
    _trusted_device,
    app_client,
    clock,
    fast_verify,
    mails,
    settings,
    slow_verify,
)


def _device_cookie_headers(response: Any, name: str = "sdp_device_student") -> list[str]:
    return [h for h in response.headers.get_list("set-cookie") if h.startswith(f"{name}=")]


def _logout(browser: TestClient, area: str = "student") -> Any:
    return browser.post(
        f"/api/{area}/auth/logout", headers={"X-CSRF-Token": browser.cookies.get("sdp_csrf") or ""}
    )


# ------------------------------------------------------- remember this device


def test_login_without_remember_sets_no_device_cookie(app_client: TestClient) -> None:
    _register(app_client, "lab@example.com")
    browser = _other(app_client, "10.1.1.1")
    r = _login(browser, "lab@example.com", remember=False)
    assert r.status_code == status.HTTP_200_OK
    assert _device_cookie_headers(r) == []
    assert browser.cookies.get("sdp_device_student") is None


def test_remember_defaults_to_off_for_api_clients(app_client: TestClient) -> None:
    _register(app_client, "api@example.com")
    r = _other(app_client, "10.1.1.2").post(
        STUDENT_LOGIN, json={"email": "api@example.com", "password": GOOD_PW}
    )
    assert r.status_code == status.HTTP_200_OK
    assert _device_cookie_headers(r) == []


def test_logout_of_an_unremembered_session_leaves_no_device_cookie(
    app_client: TestClient,
) -> None:
    """B was remembered on this PC once; later B signs in without remembering
    and logs out — B's own device cookie goes too."""
    _register(app_client, "b@example.com")
    pc = _trusted_device(app_client, "b@example.com", ip="10.1.2.1")
    assert pc.cookies.get("sdp_device_student")
    assert _login(pc, "b@example.com", remember=False).status_code == status.HTTP_200_OK
    out = _logout(pc)
    assert out.status_code == status.HTTP_204_NO_CONTENT
    cleared = _device_cookie_headers(out)
    assert cleared and "max-age=0" in cleared[0].lower()
    assert pc.cookies.get("sdp_device_student") is None


def test_logout_keeps_a_device_cookie_of_another_account(app_client: TestClient) -> None:
    """Controller ruling 2026-10-29: shared lab PC, A was remembered here; B
    signs in without remembering and logs out — A's trust stays."""
    _register(app_client, "a2@example.com")
    _register(app_client, "b2@example.com")
    pc = _trusted_device(app_client, "a2@example.com", ip="10.1.2.2")
    a_cookie = pc.cookies.get("sdp_device_student")
    assert a_cookie
    assert _login(pc, "b2@example.com", remember=False).status_code == status.HTTP_200_OK
    out = _logout(pc)
    assert out.status_code == status.HTTP_204_NO_CONTENT
    assert _device_cookie_headers(out) == []
    assert pc.cookies.get("sdp_device_student") == a_cookie


def test_logout_of_a_remembered_session_keeps_the_device_cookie(app_client: TestClient) -> None:
    _register(app_client, "home@example.com")
    laptop = _other(app_client, "10.1.3.1")
    assert _login(laptop, "home@example.com").status_code == status.HTTP_200_OK
    out = _logout(laptop)
    assert out.status_code == status.HTTP_204_NO_CONTENT
    assert _device_cookie_headers(out) == []
    assert laptop.cookies.get("sdp_device_student")


def test_admin_login_honours_remember_too(app_client: TestClient, db_session: Session) -> None:
    from app.cli import seed_admin

    seed_admin(db_session, email="boss@example.com", display_name="B", password="admin-pw-12345")
    db_session.flush()
    browser = _other(app_client, "10.1.4.1")
    r = _login(
        browser, "boss@example.com", "admin-pw-12345", "/api/admin/auth/login", remember=False
    )
    assert r.status_code == status.HTTP_200_OK
    assert _device_cookie_headers(r, "sdp_device_admin") == []
    browser.cookies.set("sdp_device_admin", "left-over-cookie")
    out = _logout(browser, "admin")
    assert out.status_code == status.HTTP_204_NO_CONTENT
    cleared = _device_cookie_headers(out, "sdp_device_admin")
    assert cleared and "max-age=0" in cleared[0].lower()


# ------------------------------------------------- alert counts device guesses


def test_failures_with_a_device_cookie_also_raise_the_alert(
    app_client: TestClient, mails: list[dict[str, str]], fast_verify: list[str]
) -> None:
    """Scenario 7: B guesses A's password on a PC that remembers A."""
    _register(app_client, "owner@example.com")
    lab_pc = _trusted_device(app_client, "owner@example.com")
    for _ in range(4):
        _login(lab_pc, "owner@example.com", BAD_PW)
    assert mails == []
    _login(lab_pc, "owner@example.com", BAD_PW)
    assert [m["to"] for m in mails] == ["owner@example.com"]


def test_alert_streak_mixes_device_and_plain_failures(
    app_client: TestClient, mails: list[dict[str, str]], fast_verify: list[str]
) -> None:
    _register(app_client, "owner@example.com")
    lab_pc = _trusted_device(app_client, "owner@example.com")
    for _ in range(3):
        _login(lab_pc, "owner@example.com", BAD_PW)
    for _ in range(2):
        _login(_other(app_client, "10.2.0.9"), "owner@example.com", BAD_PW)
    assert len(mails) == 1


def test_concurrent_failures_send_one_alert(
    app_client: TestClient, mails: list[dict[str, str]], slow_verify: list[str]
) -> None:
    """Scenario 9: failures 5 and 6 land together; one mail, not two."""
    _register(app_client, "owner@example.com")
    for _ in range(4):
        _login(_other(app_client, "10.2.1.1"), "owner@example.com", BAD_PW)
    results = _burst(app_client, "owner@example.com", 12)
    assert sum(r.status_code == status.HTTP_401_UNAUTHORIZED for r in results) == 2
    assert len(mails) == 1


# ------------------------------------------ trusted success vs. the attacker


def test_trusted_success_keeps_the_attackers_email_delay(
    app_client: TestClient, clock: FakeClock, fast_verify: list[str]
) -> None:
    """Scenario 8: the owner signing in from their own browser mustn't hand
    the attacker five fresh free guesses."""
    _register(app_client, "owner@example.com")
    laptop = _trusted_device(app_client, "owner@example.com")
    attacker = _lock_email(app_client, "owner@example.com")
    assert _login(laptop, "owner@example.com").status_code == status.HTTP_200_OK
    r = _login(attacker, "owner@example.com", BAD_PW)
    assert r.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    clock.advance(2)
    assert _login(attacker, "owner@example.com", BAD_PW).status_code == 401
    # still on the schedule: the next wait is longer, not free again
    assert _login(attacker, "owner@example.com", BAD_PW).json()["error"]["retry_after"] == 4


def test_untrusted_success_still_clears_the_email_count(
    app_client: TestClient, clock: FakeClock, fast_verify: list[str]
) -> None:
    _register(app_client, "owner@example.com")
    browser = _other(app_client, "10.3.3.3")
    for _ in range(6):
        _login(browser, "owner@example.com", BAD_PW, remember=False)
    clock.advance(2)
    assert _login(browser, "owner@example.com", remember=False).status_code == 200
    codes = [_login(browser, "owner@example.com", BAD_PW).status_code for _ in range(5)]
    assert codes == [401] * 5


# ------------------------------------------------- reset makes a trusted device


def test_reset_confirm_trusts_the_redeeming_browser(
    app_client: TestClient, db_session: Session, redis_client: Any, fast_verify: list[str]
) -> None:
    """Scenario 6: the alert mail's advice (reset) must not lock the owner out
    while the attack goes on; other devices stay revoked."""
    _register(app_client, "owner@example.com")
    old_laptop = _trusted_device(app_client, "owner@example.com", ip="10.4.0.1")
    _lock_email(app_client, "owner@example.com")

    owner = _student(db_session, "owner@example.com")
    token = password_reset.issue_reset_token(redis_client, user_id=owner.id, scope="student")
    phone = _other(app_client, "10.4.0.2")
    new_pw = "brand-new-pass-456"
    r = phone.post(
        "/api/student/auth/password-reset/confirm", json={"token": token, "password": new_pw}
    )
    assert r.status_code == status.HTTP_204_NO_CONTENT
    header = _device_cookie_headers(r)
    assert header and "httponly" in header[0].lower()
    # no session is opened by the reset itself
    assert phone.cookies.get("sdp_student") is None

    assert _login(phone, "owner@example.com", new_pw).status_code == status.HTTP_200_OK
    assert _login(old_laptop, "owner@example.com", new_pw).status_code == (
        status.HTTP_429_TOO_MANY_REQUESTS
    )


def test_admin_reset_confirm_sets_the_admin_device_cookie(
    app_client: TestClient, db_session: Session, redis_client: Any
) -> None:
    from app.cli import seed_admin

    admin, _ = seed_admin(
        db_session, email="boss@example.com", display_name="B", password="admin-pw-12345"
    )
    db_session.flush()
    token = password_reset.issue_reset_token(redis_client, user_id=admin.id, scope="admin")
    r = _other(app_client, "10.4.1.1").post(
        "/api/admin/auth/password-reset/confirm",
        json={"token": token, "password": "brand-new-pass-456"},
    )
    assert r.status_code == status.HTTP_204_NO_CONTENT
    assert _device_cookie_headers(r, "sdp_device_admin")
    assert _device_cookie_headers(r) == []


def test_a_failed_reset_sets_no_device_cookie(app_client: TestClient) -> None:
    r = _other(app_client, "10.4.2.1").post(
        "/api/student/auth/password-reset/confirm",
        json={"token": "bogus", "password": "brand-new-pass-456"},
    )
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert _device_cookie_headers(r) == []


# --------------------------------------------- previous session on re-login


def test_signing_in_destroys_the_previous_session_in_this_browser(
    app_client: TestClient,
) -> None:
    """Scenario 17: A never logged out on the shared PC; B signs in there."""
    _register(app_client, "a@example.com")
    _register(app_client, "b@example.com")
    pc = _other(app_client, "10.5.0.1")
    assert _login(pc, "a@example.com").status_code == status.HTTP_200_OK
    a_token = pc.cookies.get("sdp_student")
    assert a_token
    assert _login(pc, "b@example.com").status_code == status.HTTP_200_OK
    copied = _other(app_client, "10.5.0.2")
    copied.cookies.set("sdp_student", a_token)
    assert copied.get("/api/student/auth/me").status_code == status.HTTP_401_UNAUTHORIZED
    assert pc.get("/api/student/auth/me").json()["user"]["email"] == "b@example.com"
