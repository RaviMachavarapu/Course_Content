import { Link, useLocation, useRouteError } from "react-router-dom";
import { ErrorState } from "@/components";

/** Where "go back" leads from a crashed screen: the area's home. */
function homeFor(pathname: string): { to: string; label: string } {
  if (pathname.startsWith("/admin")) return { to: "/admin/ingestion", label: "Back to Ingestion" };
  const learn = pathname.match(/^\/learn\/([^/]+)/);
  if (learn) return { to: `/learn/${learn[1]}`, label: "Back to Course Overview" };
  return { to: "/catalog", label: "Back to Catalog" };
}

/**
 * Route `errorElement`: a render error (e.g. content in an unexpected shape)
 * shows this inside the surrounding shell instead of React Router's
 * full-screen "Unexpected Application Error!".
 */
export function RouteError(): JSX.Element {
  const error = useRouteError();
  const { pathname } = useLocation();
  const home = homeFor(pathname);
  if (import.meta.env.DEV) console.error(error);
  return (
    <div className="flex flex-1 flex-col items-center gap-4 p-4 md:p-margin-desktop">
      <ErrorState
        className="w-full max-w-xl"
        title="This page couldn’t be shown"
        description="Something in this content couldn’t be displayed. Try reloading, or go back."
        onRetry={() => window.location.reload()}
      />
      <Link
        to={home.to}
        className="font-label-md text-label-md text-tertiary underline underline-offset-4"
      >
        {home.label}
      </Link>
    </div>
  );
}
