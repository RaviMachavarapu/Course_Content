"""Admin API package.

Every admin **feature** router (courses, staging, settings, users, …) must be
mounted with `ADMIN_DEPENDENCIES`, which enforces a valid admin session
(`current_admin`) and CSRF on state-changing requests. The auth router
(`admin.auth`) is the one exception — it predates the session.
"""

from fastapi import Depends

from app.api.deps import current_admin
from app.auth.csrf import csrf_protect

ADMIN_DEPENDENCIES = [Depends(current_admin), Depends(csrf_protect)]

__all__ = ["ADMIN_DEPENDENCIES"]
