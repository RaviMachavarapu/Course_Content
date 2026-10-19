import { Link } from "react-router-dom";
import { Card, EmptyState, ErrorState, Icon, Skeleton } from "@/components";
import { StatusChip } from "../AdminStatus";
import { useCourses } from "../useAdminApi";

export function EditorPage(): JSX.Element {
  const courses = useCourses();

  return (
    <div className="flex flex-1 flex-col gap-6 p-4 md:p-margin-desktop">
      <div>
        <h1 className="font-headline-lg text-headline-lg text-on-background">Course Editor</h1>
        <p className="mt-1 text-body-md text-on-surface-variant">
          Pick a course to edit its module structure.
        </p>
      </div>

      {courses.isError && <ErrorState title="Could not load courses" onRetry={() => void courses.refetch()} />}

      {courses.isPending && (
        <div className="grid gap-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-16" />
          ))}
        </div>
      )}

      {courses.data && courses.data.length === 0 && (
        <EmptyState
          icon="library_books"
          title="No courses yet"
          description="Create one from the Ingestion Portal."
          action={
            <Link
              to="/admin/ingestion"
              className="font-label-md text-label-md text-primary underline underline-offset-4"
            >
              Go to Ingestion
            </Link>
          }
        />
      )}

      {courses.data && courses.data.length > 0 && (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-body-md">
              <thead className="border-b border-outline-variant font-label-sm text-label-sm text-on-surface-variant">
                <tr>
                  <th className="px-4 py-2">Course</th>
                  <th className="px-4 py-2">Modules</th>
                  <th className="px-4 py-2">Status</th>
                  <th className="px-4 py-2">Updated</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {courses.data.map((c) => (
                  <tr key={c.id} className="border-b border-outline-variant/60">
                    <td className="px-4 py-3">
                      <Link
                        to={`/admin/editor/${c.id}`}
                        data-testid="editor-course-link"
                        className="font-label-md text-label-md text-primary hover:underline"
                      >
                        {c.title}
                      </Link>
                      <div className="text-label-sm text-on-surface-variant">{c.category || "—"}</div>
                    </td>
                    <td className="px-4 py-3 text-on-surface-variant">{c.module_count}</td>
                    <td className="px-4 py-3">
                      <StatusChip status={c.status} />
                    </td>
                    <td className="px-4 py-3 text-label-sm text-on-surface-variant">
                      {new Date(c.updated_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <Link
                        to={`/admin/editor/${c.id}`}
                        className="inline-flex items-center gap-1 font-label-md text-label-md text-primary hover:underline"
                      >
                        Edit structure
                        <Icon name="arrow_forward" className="text-[16px]" />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
