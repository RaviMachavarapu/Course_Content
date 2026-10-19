import { Link } from "react-router-dom";
import { Icon } from "@/components";
import { ARTIFACT_LABELS, type RecentJob } from "./api";
import { useRecentJobs } from "./useAdminApi";

function ago(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86_400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86_400)}d ago`;
}

function label(job: RecentJob): string {
  const what = job.artifact_type ? ARTIFACT_LABELS[job.artifact_type] : "Module";
  return `${what} ${job.state === "succeeded" ? "ready" : "failed"}`;
}

export function NotificationsPanel({ onNavigate }: { onNavigate: () => void }): JSX.Element {
  const { data, isPending, isError } = useRecentJobs();

  return (
    <div
      role="menu"
      className="absolute right-0 z-40 mt-1 w-80 overflow-hidden rounded-lg border border-outline-variant bg-surface-container-lowest shadow-level-2"
    >
      <div className="border-b border-outline-variant px-4 py-2 font-label-md text-label-md text-on-surface-variant">
        Notifications
      </div>
      <div className="max-h-96 overflow-y-auto">
        {isPending && <p className="px-4 py-6 text-center text-body-sm text-on-surface-variant">Loading…</p>}
        {isError && (
          <p className="px-4 py-6 text-center text-body-sm text-error">Could not load notifications.</p>
        )}
        {data && data.length === 0 && (
          <p className="px-4 py-6 text-center text-body-sm text-on-surface-variant">
            No recent generation activity.
          </p>
        )}
        {data?.map((job) => {
          const row = (
            <div className="flex gap-2 px-4 py-3 hover:bg-surface-container-high">
              <Icon
                name={job.state === "succeeded" ? "check_circle" : "error"}
                filled
                className={job.state === "succeeded" ? "text-secondary" : "text-error"}
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-label-md text-label-md">{label(job)}</span>
                  <span className="shrink-0 text-label-sm text-on-surface-variant">{ago(job.at)}</span>
                </div>
                <div className="truncate text-label-sm text-on-surface-variant">
                  {job.module_title ?? "—"}
                </div>
                {job.state === "failed" && job.error_detail && (
                  <div className="mt-0.5 truncate text-label-sm text-error">{job.error_detail}</div>
                )}
              </div>
            </div>
          );
          return job.module_id ? (
            <Link
              key={job.id}
              to={`/admin/modules/${job.module_id}/staging`}
              onClick={onNavigate}
              data-testid="notif-row"
            >
              {row}
            </Link>
          ) : (
            <div key={job.id} data-testid="notif-row">
              {row}
            </div>
          );
        })}
      </div>
    </div>
  );
}
