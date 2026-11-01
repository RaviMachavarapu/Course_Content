import { useNavigate } from "react-router-dom";
import { Button } from "@/components";
import { useLogout } from "./useStudentAuth";

/** The student "Log out" button (owner decisions 4 and 10: on every student page). */
export function LogoutButton({ testid = "btn-logout" }: { testid?: string }): JSX.Element {
  const navigate = useNavigate();
  const logout = useLogout();
  return (
    <Button
      variant="secondary"
      size="sm"
      iconLeft="logout"
      data-testid={testid}
      loading={logout.isPending}
      onClick={() =>
        logout.mutate(undefined, {
          // only on success: a failed logout leaves the session live, and the
          // hook tells the user so
          onSuccess: () => navigate("/login", { replace: true }),
        })
      }
    >
      Log out
    </Button>
  );
}
