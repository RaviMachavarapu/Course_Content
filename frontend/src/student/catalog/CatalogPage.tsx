import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Icon, TopBar } from "@/components";
import { useLogout } from "../auth/useStudentAuth";

function ProfileMenu(): JSX.Element {
  const navigate = useNavigate();
  const logout = useLogout();
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        aria-label="Profile menu"
        data-testid="btn-ct5"
        onClick={() => setOpen((v) => !v)}
        className="flex h-8 w-8 items-center justify-center rounded-full bg-tertiary text-on-tertiary focus-visible:outline-none focus-visible:shadow-focus"
      >
        <Icon name="person" filled className="text-[18px]" />
      </button>
      {open && (
        <>
          <button
            aria-hidden="true"
            tabIndex={-1}
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-30 cursor-default"
          />
          <div className="absolute right-0 z-40 mt-1 w-40 rounded-lg border border-outline-variant bg-surface-container-lowest py-1 shadow-level-2">
            <button
              onClick={() =>
                logout.mutate(undefined, {
                  // only on success: a failed logout leaves the session live,
                  // and the hook tells the user so
                  onSuccess: () => navigate("/login", { replace: true }),
                  onError: () => setOpen(false),
                })
              }
              className="flex w-full items-center gap-2 px-3 py-2 text-left font-label-md text-label-md hover:bg-surface-container-high focus-visible:outline-none focus-visible:shadow-focus"
            >
              <Icon name="logout" className="text-[18px]" />
              Log out
            </button>
          </div>
        </>
      )}
    </div>
  );
}

export function CatalogPage(): JSX.Element {
  return <TopBar title="Course Catalogs" right={<ProfileMenu />} />;
}
