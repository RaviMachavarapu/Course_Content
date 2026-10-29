import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Icon } from "@/components";
import { useUIStore } from "@/lib/store";
import { useAdminLogout } from "./auth/useAdminAuth";
import { McpBadge, WorkerBadge } from "./AdminStatus";
import { NotificationsPanel } from "./NotificationsPanel";
import { useMcpStatus, useRecentJobs } from "./useAdminApi";

export function AdminHeader(): JSX.Element {
  const navigate = useNavigate();
  const mcp = useMcpStatus();
  const jobs = useRecentJobs();
  const logout = useAdminLogout();
  const setSidebarOpen = useUIStore((s) => s.setSidebarOpen);
  const [menuOpen, setMenuOpen] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);

  const failureCount = (jobs.data ?? []).filter((j) => j.state === "failed").length;

  return (
    <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-outline-variant bg-surface-container-lowest px-4 py-3 md:px-margin-desktop">
      <button
        aria-label="Open menu"
        className="rounded-lg p-1 text-on-surface-variant hover:bg-surface-container-high lg:hidden"
        onClick={() => setSidebarOpen(true)}
      >
        <Icon name="menu" />
      </button>

      <div className="flex flex-1 items-center gap-3">
        <McpBadge
          healthy={mcp.data?.healthy}
          isFixture={mcp.data?.account_email === "fixture@localhost"}
        />
        <WorkerBadge stale={mcp.data?.worker_heartbeat_stale} />
      </div>

      <div className="flex items-center gap-1">
        <Link
          to="/admin/settings"
          aria-label="Settings"
          data-testid="btn-ig7"
          className="rounded-full p-2 text-on-surface-variant hover:bg-surface-container-high"
        >
          <Icon name="settings" />
        </Link>
        <div className="relative">
          <button
            aria-label="Notifications"
            aria-expanded={notifOpen}
            data-testid="btn-ig8"
            onClick={() => {
              setMenuOpen(false);
              setNotifOpen((v) => !v);
            }}
            className="relative rounded-full p-2 text-on-surface-variant hover:bg-surface-container-high"
          >
            <Icon name="notifications" />
            {failureCount > 0 && (
              <span
                data-testid="notif-badge"
                className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-error px-1 text-[10px] font-bold text-on-error"
              >
                {failureCount}
              </span>
            )}
          </button>
          {notifOpen && (
            <>
              <button
                aria-hidden="true"
                tabIndex={-1}
                onClick={() => setNotifOpen(false)}
                className="fixed inset-0 z-30 cursor-default"
              />
              <NotificationsPanel onNavigate={() => setNotifOpen(false)} />
            </>
          )}
        </div>
        <div className="relative">
          <button
            aria-label="Account menu"
            data-testid="btn-ig9"
            onClick={() => setMenuOpen((v) => !v)}
            className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-on-primary"
          >
            <Icon name="person" filled className="text-[18px]" />
          </button>
          {menuOpen && (
            <div className="absolute right-0 mt-1 w-40 rounded-lg border border-outline-variant bg-surface-container-lowest py-1 shadow-level-2">
              <button
                onClick={() => {
                  logout.mutate(undefined, {
                    // only on success: a failed logout leaves the session live,
                    // and the hook tells the user so
                    onSuccess: () => navigate("/admin/login", { replace: true }),
                    onError: () => setMenuOpen(false),
                  });
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-left font-label-md text-label-md hover:bg-surface-container-high"
              >
                <Icon name="logout" className="text-[18px]" />
                Log out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
