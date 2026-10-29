import { Link } from "react-router-dom";
import { Card, EmptyState, ErrorState, Icon, ProgressBar, Skeleton, TopBar } from "@/components";
import { useMyListening } from "./useMe";
import { LogoutButton } from "../auth/LogoutButton";

function fmt(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function MyListeningPage(): JSX.Element {
  const { data, isPending, isError, refetch } = useMyListening();

  return (
    <>
      <TopBar title="My Listening" right={<LogoutButton />} />
      <div className="flex flex-1 flex-col gap-5 p-4 md:p-margin-desktop">
        <p className="text-body-md text-on-surface-variant">
          Audio overviews you've started, and how far you've gotten.
        </p>

        {isPending && (
          <div className="flex flex-col gap-3">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-20" />
            ))}
          </div>
        )}

        {isError && (
          <ErrorState title="Could not load your listening" onRetry={() => void refetch()} />
        )}

        {data && data.length === 0 && (
          <EmptyState
            icon="headphones"
            title="Nothing playing yet"
            description="Open an Audio Overview from a course to see it here."
          />
        )}

        {data && data.length > 0 && (
          <div className="flex flex-col gap-3">
            {data.map((row) => (
              <Card key={row.artifact_id} className="p-4" data-testid="listening-row">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="font-label-lg text-label-lg">{row.course_title}</p>
                    <p className="text-label-sm text-on-surface-variant">{row.module_title}</p>
                  </div>
                  <Link
                    to={`/learn/${row.course_slug}/${row.module_index}/audio_overview`}
                    data-testid="btn-ml1"
                    className="inline-flex items-center gap-1.5 rounded-lg bg-tertiary px-3 py-1.5 font-label-md text-label-md text-on-tertiary hover:bg-tertiary/90"
                  >
                    <Icon name="play_arrow" className="text-[18px]" />
                    Resume
                  </Link>
                </div>
                <div className="mt-3 flex items-center gap-3">
                  <ProgressBar
                    value={row.percent_listened}
                    tone={row.completed ? "complete" : "active"}
                    className="flex-1"
                  />
                  <span className="font-label-sm text-label-sm tabular-nums text-on-surface-variant">
                    {fmt(row.audio_position_seconds)} / {fmt(row.duration_seconds)}
                  </span>
                  {row.completed && (
                    <Icon name="check_circle" filled className="text-[18px] text-secondary" />
                  )}
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
