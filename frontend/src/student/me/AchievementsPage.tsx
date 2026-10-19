import { Card, ErrorState, Icon, Skeleton, TopBar } from "@/components";
import { cn } from "@/lib/cn";
import type { Achievement } from "./api";
import { useMyAchievements } from "./useMe";

function Badge({ badge }: { badge: Achievement }): JSX.Element {
  return (
    <Card
      className={cn("flex flex-col items-center gap-2 p-5 text-center", !badge.earned && "opacity-50")}
      data-testid="achievement-badge"
      data-earned={badge.earned}
    >
      <div
        className={cn(
          "flex h-14 w-14 items-center justify-center rounded-full",
          badge.earned ? "bg-tertiary text-on-tertiary" : "bg-surface-container-high text-on-surface-variant",
        )}
      >
        <Icon name={badge.icon} filled={badge.earned} className="text-[28px]" />
      </div>
      <p className="font-label-lg text-label-lg">{badge.label}</p>
      <p className="text-label-sm text-on-surface-variant">{badge.description}</p>
      {badge.earned && badge.earned_at && (
        <p className="font-label-sm text-label-sm text-tertiary">
          Earned {new Date(badge.earned_at).toLocaleDateString()}
        </p>
      )}
      {!badge.earned && (
        <p className="font-label-sm text-label-sm text-on-surface-variant">Locked</p>
      )}
    </Card>
  );
}

export function AchievementsPage(): JSX.Element {
  const { data, isPending, isError, refetch } = useMyAchievements();

  return (
    <>
      <TopBar title="Achievements" />
      <div className="flex flex-1 flex-col gap-6 p-4 md:p-margin-desktop">
        <p className="text-body-md text-on-surface-variant">
          Badges you've earned, and what unlocks the rest.
        </p>

        {isPending && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-40" />
            ))}
          </div>
        )}

        {isError && (
          <ErrorState title="Could not load achievements" onRetry={() => void refetch()} />
        )}

        {data && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[...data.earned, ...data.locked].map((badge) => (
              <Badge key={badge.key} badge={badge} />
            ))}
          </div>
        )}
      </div>
    </>
  );
}
