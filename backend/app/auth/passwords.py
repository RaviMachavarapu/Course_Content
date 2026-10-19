"""Password strength policy for student registration (spec.md §3.7).

Deliberately simple and predictable so the client can mirror it exactly:
at least 10 characters, containing at least one letter and one non-letter.
"""

from __future__ import annotations

from fastapi import status

from app.errors import APIError

MIN_LENGTH = 10


def password_problems(password: str) -> list[str]:
    problems: list[str] = []
    if len(password) < MIN_LENGTH:
        problems.append(f"must be at least {MIN_LENGTH} characters")
    if not any(c.isalpha() for c in password):
        problems.append("must contain a letter")
    if not any(not c.isalpha() for c in password):
        problems.append("must contain a number or symbol")
    return problems


def validate_password_strength(password: str) -> None:
    problems = password_problems(password)
    if problems:
        raise APIError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "weak_password",
            "Password " + "; ".join(problems) + ".",
        )
