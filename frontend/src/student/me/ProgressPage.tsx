import { Link } from "react-router-dom";
import { Card, EmptyState, ErrorState, ProgressBar, Skeleton, TopBar } from "@/components";
import { useMyProgress } from "./useMe";

export function ProgressPage(): JSX.Element {
  const { data, isPending, isError, refetch } = useMyProgress();

  return (
    <>
      <TopBar title="Progress" />
      <div className="flex flex-1 flex-col gap-5 p-4 md:p-margin-desktop">
        <p className="text-body-md text-on-surface-variant">
          How far you've gotten in every course you've started.
        </p>

        {isPending && (
          <div className="flex flex-col gap-3">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-20" />
            ))}
          </div>
        )}

        {isError && <ErrorState title="Could not load your progress" onRetry={() => void refetch()} />}

        {data && data.length === 0 && (
          <EmptyState
            icon="trending_up"
            title="Nothing started yet"
            description="Open a course from the catalog to begin tracking progress."
            action={
              <Link
                to="/catalog"
                className="font-label-md text-label-md text-tertiary underline underline-offset-4"
              >
                Browse the catalog
              </Link>
            }
          />
        )}

        {data && data.length > 0 && (
          <div className="flex flex-col gap-3">
            {data.map((c) => (
              <Card key={c.id} className="p-4" data-testid="progress-row">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <Link
                    to={`/learn/${c.slug}`}
                    className="font-label-lg text-label-lg hover:text-tertiary"
                  >
                    {c.title}
                  </Link>
                  <span className="font-label-sm text-label-sm text-on-surface-variant">
                    {c.modules_started} of {c.modules_total} units started
                  </span>
                </div>
                <div className="mt-3 flex items-center gap-3">
                  <ProgressBar
                    value={c.percent_complete}
                    tone={c.percent_complete >= 100 ? "complete" : "active"}
                    className="flex-1"
                  />
                  <span className="font-label-sm text-label-sm tabular-nums text-on-surface-variant">
                    {c.percent_complete}%
                  </span>
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
