import { Navigate, Outlet, useLocation } from "react-router-dom";
import { EmptyState, Skeleton, TopBar } from "@/components";
import { AdminLayout } from "@/admin/AdminLayout";
import { useAdminSession } from "@/admin/auth/useAdminAuth";
import { StudentChrome } from "@/student/StudentChrome";
import { StudentLayout } from "@/student/StudentLayout";
import { useStudentSession } from "@/student/auth/useStudentAuth";

function FullPageLoading(): JSX.Element {
  return (
    <div className="flex min-h-screen items-center justify-center bg-surface">
      <Skeleton className="h-6 w-40" />
    </div>
  );
}

/** Student-facing 404 — used when a student hits an `/admin/*` URL (US-N3):
 * the admin area must not even acknowledge itself to non-admins. */
function StudentNotFound(): JSX.Element {
  return (
    <StudentChrome>
      <TopBar title="Not found" />
      <div className="flex-1 p-4 md:p-margin-desktop">
        <EmptyState
          icon="explore_off"
          title="Page not found"
          description="The page you’re looking for doesn’t exist."
        />
      </div>
    </StudentChrome>
  );
}

/**
 * Gate for the `/admin` route tree:
 * - valid admin session  -> render the admin shell
 * - a student session     -> student 404, no admin chrome (US-N3)
 * - otherwise (anonymous) -> redirect to `/admin/login`
 */
export function RequireAdmin(): JSX.Element {
  const location = useLocation();
  const admin = useAdminSession();
  const student = useStudentSession();

  if (admin.isPending || student.isPending) return <FullPageLoading />;
  if (admin.user) return <AdminLayout />;
  if (student.user) return <StudentNotFound />;
  return <Navigate to="/admin/login" replace state={{ from: location.pathname }} />;
}

/**
 * Gate for the student route tree (`/catalog`, `/learn/*`, …):
 * a valid student session renders the student shell; anyone else is sent to
 * `/login`.
 */
export function RequireStudent(): JSX.Element {
  const location = useLocation();
  const student = useStudentSession();

  if (student.isPending) return <FullPageLoading />;
  if (student.user) return <StudentLayout />;
  return <Navigate to="/login" replace state={{ from: location.pathname }} />;
}

/** Student session gate that renders a bare `<Outlet />` — for route trees
 * (e.g. the course workspace) that bring their own chrome. */
export function RequireStudentRaw(): JSX.Element {
  const location = useLocation();
  const student = useStudentSession();

  if (student.isPending) return <FullPageLoading />;
  if (student.user) return <Outlet />;
  return <Navigate to="/login" replace state={{ from: location.pathname }} />;
}
