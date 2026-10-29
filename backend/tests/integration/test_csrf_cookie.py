"""The `sdp_csrf` cookie lives as long as the sessions it protects (review 2026-10-28).

It used to be a browser-session cookie while the auth cookies persisted, so
after a browser restart every mutation (and logout) failed with 403. It is one
cookie shared by both areas, so one area's logout must not delete it while the
other area's session is still alive, and an authenticated `/me` re-issues it.
"""

from __future__ import annotations

from http.cookies import SimpleCookie

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cli import seed_admin
from app.config import get_settings

STUDENT = {"email": "stu@example.com", "password": "student-pw-12345", "display_name": "Stu"}
ADMIN_PW = "admin-console-pw-1"


def _csrf_set_cookie(resp: object) -> SimpleCookie | None:
    for raw in resp.headers.get_list("set-cookie"):  # type: ignore[attr-defined]
        if raw.startswith("sdp_csrf="):
            jar: SimpleCookie = SimpleCookie()
            jar.load(raw)
            return jar
    return None


def _max_age(resp: object) -> int:
    jar = _csrf_set_cookie(resp)
    assert jar is not None, "no sdp_csrf Set-Cookie"
    return int(jar["sdp_csrf"]["max-age"])


def _longest_session_seconds() -> int:
    s = get_settings()
    return max(s.admin_session_ttl_hours * 3600, s.student_session_ttl_days * 86400)


def _admin_login(client: TestClient, db_session: Session) -> object:
    seed_admin(db_session, email="boss@example.com", display_name="Boss", password=ADMIN_PW)
    db_session.flush()
    r = client.post(
        "/api/admin/auth/login", json={"email": "boss@example.com", "password": ADMIN_PW}
    )
    assert r.status_code == status.HTTP_200_OK
    return r


def test_register_and_login_set_a_persistent_csrf_cookie(
    client: TestClient, db_session: Session
) -> None:
    reg = client.post("/api/student/auth/register", json=STUDENT)
    assert _max_age(reg) == _longest_session_seconds()
    client.cookies.clear()
    login = client.post(
        "/api/student/auth/login", json={"email": STUDENT["email"], "password": STUDENT["password"]}
    )
    assert _max_age(login) == _longest_session_seconds()
    assert _max_age(_admin_login(client, db_session)) == _longest_session_seconds()


def test_me_reissues_a_missing_csrf_cookie(client: TestClient) -> None:
    """A browser that lost the cookie (old session-only cookie, restart) gets a
    fresh one from /me, so mutations and logout work again."""
    client.post("/api/student/auth/register", json=STUDENT)
    del client.cookies["sdp_csrf"]
    assert client.post("/api/student/auth/logout").status_code == status.HTTP_403_FORBIDDEN

    me = client.get("/api/student/auth/me")
    assert me.status_code == status.HTTP_200_OK
    assert _max_age(me) == _longest_session_seconds()
    token = client.cookies["sdp_csrf"]
    out = client.post("/api/student/auth/logout", headers={"X-CSRF-Token": token})
    assert out.status_code == status.HTTP_204_NO_CONTENT


def test_me_keeps_an_existing_csrf_value_and_refreshes_its_lifetime(
    client: TestClient, db_session: Session
) -> None:
    _admin_login(client, db_session)
    before = client.cookies["sdp_csrf"]
    me = client.get("/api/admin/auth/me")
    assert me.status_code == status.HTTP_200_OK
    jar = _csrf_set_cookie(me)
    assert jar is not None and jar["sdp_csrf"].value == before
    assert client.cookies["sdp_csrf"] == before


def test_anonymous_me_does_not_issue_a_csrf_cookie(client: TestClient) -> None:
    me = client.get("/api/student/auth/me")
    assert me.status_code == status.HTTP_401_UNAUTHORIZED
    assert _csrf_set_cookie(me) is None


def test_student_logout_keeps_the_csrf_cookie_while_an_admin_session_lives(
    client: TestClient, db_session: Session
) -> None:
    client.post("/api/student/auth/register", json=STUDENT)
    _admin_login(client, db_session)
    token = client.cookies["sdp_csrf"]

    out = client.post("/api/student/auth/logout", headers={"X-CSRF-Token": token})
    assert out.status_code == status.HTTP_204_NO_CONTENT
    assert _csrf_set_cookie(out) is None  # not deleted
    assert client.cookies["sdp_csrf"] == token

    # the admin can still mutate (and log out)
    admin_out = client.post("/api/admin/auth/logout", headers={"X-CSRF-Token": token})
    assert admin_out.status_code == status.HTTP_204_NO_CONTENT
    assert "sdp_csrf" not in client.cookies  # last session gone → cleared


def test_admin_logout_keeps_the_csrf_cookie_while_a_student_session_lives(
    client: TestClient, db_session: Session
) -> None:
    _admin_login(client, db_session)
    client.post("/api/student/auth/register", json=STUDENT)
    token = client.cookies["sdp_csrf"]

    out = client.post("/api/admin/auth/logout", headers={"X-CSRF-Token": token})
    assert out.status_code == status.HTTP_204_NO_CONTENT
    assert client.cookies["sdp_csrf"] == token
    assert client.get("/api/student/auth/me").status_code == status.HTTP_200_OK


def test_logout_alone_clears_the_csrf_cookie(client: TestClient) -> None:
    client.post("/api/student/auth/register", json=STUDENT)
    token = client.cookies["sdp_csrf"]
    out = client.post("/api/student/auth/logout", headers={"X-CSRF-Token": token})
    assert out.status_code == status.HTTP_204_NO_CONTENT
    assert "sdp_csrf" not in client.cookies
