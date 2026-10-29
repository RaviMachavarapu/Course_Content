import { Link, useOutletContext } from "react-router-dom";
import { Card, ProgressBar } from "@/components";
import { ARTIFACT_META, WORKSPACE_ARTIFACT_ORDER } from "./artifactMeta";
import type { WorkspaceContext } from "./WorkspaceLayout";

export function OverviewPanel(): JSX.Element {
  const { course } = useOutletContext<WorkspaceContext>();

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="font-headline-lg text-headline-lg [overflow-wrap:anywhere]">
          {course.title}
        </h1>
        {course.description && (
          <p className="mt-1 max-w-2xl text-body-md text-on-surface-variant">
            {course.description}
          </p>
        )}
        <div className="mt-3 max-w-md">
          <ProgressBar value={course.percent_complete} showLabel />
        </div>
      </div>

      <div className="flex flex-col gap-3">
        {course.modules.map((m) => {
          const first = WORKSPACE_ARTIFACT_ORDER.find((t) => m.artifacts.some((a) => a.type === t));
          return (
            <Card key={m.id} className="p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="font-label-sm text-label-sm text-on-surface-variant">
                    Unit {m.index + 1}
                  </p>
                  <p className="font-label-lg text-label-lg [overflow-wrap:anywhere]">{m.title}</p>
                </div>
                {first && (
                  <Link
                    to={`/learn/${course.slug}/${m.index}/${first}`}
                    data-testid="overview-open-module"
                    className="rounded-lg bg-tertiary px-3 py-1.5 font-label-md text-label-md text-on-tertiary"
                  >
                    {m.percent_complete > 0 ? "Continue" : "Start"}
                  </Link>
                )}
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <ProgressBar value={m.percent_complete} className="min-w-40 flex-1" />
                <span className="font-label-sm text-label-sm text-on-surface-variant">
                  {m.artifacts.map((a) => ARTIFACT_META[a.type].label).join(" · ")}
                </span>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
