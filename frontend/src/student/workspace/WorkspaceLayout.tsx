import { Link, Outlet, useParams } from "react-router-dom";
import { ErrorState, Icon, Skeleton } from "@/components";
import { LogoutButton } from "../auth/LogoutButton";
import type { ArtifactType } from "../catalog/api";
import type { WorkspaceCourse } from "./api";
import { ModuleExplorer } from "./ModuleExplorer";
import { useWorkspaceCourse } from "./useWorkspace";

export interface WorkspaceContext {
  course: WorkspaceCourse;
}

export function WorkspaceLayout(): JSX.Element {
  const { slug = "", moduleIndex, type } = useParams();
  const { data: course, isPending, isError, error, refetch } = useWorkspaceCourse(slug);

  if (isPending) {
    return (
      <div className="min-h-screen bg-background p-6">
        <Skeleton className="h-10 w-full max-w-3xl" />
      </div>
    );
  }

  // a failed background refresh keeps the page (and the open viewer) as it is
  if (!course) {
    const notFound =
      error && typeof error === "object" && "status" in error && error.status === 404;
    return (
      <div className="min-h-screen bg-background p-6">
        <ErrorState
          title={notFound ? "Course not available" : "Could not load the course"}
          description={notFound ? "This course isn’t published, or the link is wrong." : undefined}
          onRetry={notFound ? undefined : () => void refetch()}
        />
        <Link
          to="/catalog"
          className="mt-4 inline-flex items-center gap-1 font-label-md text-label-md text-tertiary"
        >
          <Icon name="arrow_back" className="text-[16px]" />
          Back to Dashboard
        </Link>
      </div>
    );
  }

  const activeModuleIndex = moduleIndex != null ? Number(moduleIndex) : course.current_module_index;

  return (
    <div className="flex min-h-screen flex-col bg-background text-on-background">
      <header className="sticky top-0 z-30 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-outline-variant bg-surface-container-lowest px-4 py-3 md:px-margin-desktop">
        <div className="flex min-w-0 flex-col">
          <span className="font-label-sm text-label-sm text-on-surface-variant">
            Individual Course
          </span>
          <Link
            to={`/learn/${course.slug}`}
            data-testid="btn-ws1"
            className="truncate font-label-lg text-label-lg font-semibold text-on-background hover:text-tertiary"
          >
            {course.title} · Course Overview
          </Link>
        </div>
        <div className="flex min-w-0 flex-wrap items-center justify-end gap-2 md:gap-4">
          <span className="font-label-md text-label-md tabular-nums text-on-surface-variant">
            {course.percent_complete}% Complete
          </span>
          <Link
            to="/catalog"
            data-testid="btn-ws2"
            className="inline-flex items-center gap-1 rounded-lg border border-outline-variant px-3 py-1.5 font-label-md text-label-md text-on-surface-variant hover:border-tertiary"
          >
            <Icon name="arrow_back" className="text-[16px]" />
            Back to Dashboard
          </Link>
          <LogoutButton testid="btn-ws9" />
        </div>
      </header>
      {isError && (
        <p
          role="status"
          className="border-b border-outline-variant bg-surface-container-high px-4 py-1.5 font-label-sm text-label-sm text-on-surface-variant md:px-margin-desktop"
        >
          Couldn’t refresh the course just now — your place is kept.{" "}
          <button
            type="button"
            className="underline underline-offset-2"
            onClick={() => void refetch()}
          >
            Try again
          </button>
        </p>
      )}

      <div className="flex flex-1 flex-col lg:flex-row">
        <ModuleExplorer
          course={course}
          activeModuleIndex={activeModuleIndex}
          activeType={type as ArtifactType | undefined}
        />
        <main className="flex-1 p-4 md:p-margin-desktop">
          <Outlet context={{ course } satisfies WorkspaceContext} />
        </main>
      </div>
    </div>
  );
}
