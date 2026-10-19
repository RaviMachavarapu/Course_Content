import { useState } from "react";
import { Link } from "react-router-dom";
import { Button, Card, EmptyState, ErrorState, Select, Skeleton } from "@/components";
import { StatusChip, StatusDot } from "../AdminStatus";
import { usePipeline } from "../useAdminApi";

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "processing", label: "Processing" },
  { value: "pending_review", label: "Pending review" },
  { value: "partially_published", label: "Partially published" },
  { value: "published", label: "Published" },
  { value: "error", label: "Error" },
];

export function PipelinePage(): JSX.Element {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const { data, isPending, isError, refetch } = usePipeline({
    page,
    status: status || undefined,
    q: q || undefined,
  });

  const pageCount = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div className="flex flex-1 flex-col gap-5 p-4 md:p-margin-desktop">
      <div className="flex items-center justify-between">
        <h1 className="font-headline-lg text-headline-lg">Pipeline</h1>
        <Link
          to="/admin/ingestion"
          className="font-label-md text-label-md text-primary underline underline-offset-4"
        >
          Back to Ingestion
        </Link>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <input
          className="rounded-lg border border-outline-variant bg-surface-container-lowest px-3 py-2 text-body-md"
          placeholder="Search title or URL"
          value={q}
          onChange={(e) => {
            setPage(1);
            setQ(e.target.value);
          }}
        />
        <div className="w-56">
          <Select
            label=""
            options={STATUS_OPTIONS}
            value={status}
            onChange={(e) => {
              setPage(1);
              setStatus(e.target.value);
            }}
          />
        </div>
      </div>

      {isError && <ErrorState title="Could not load the pipeline" onRetry={() => void refetch()} />}

      {isPending && (
        <div className="flex flex-col gap-2">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-14" />
          ))}
        </div>
      )}

      {data && data.rows.length === 0 && (
        <EmptyState
          icon="filter_alt_off"
          title="No modules match"
          description="Try a different search or status filter."
        />
      )}

      {data && data.rows.length > 0 && (
        <>
          <Card>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-body-md">
                <thead className="border-b border-outline-variant font-label-sm text-label-sm text-on-surface-variant">
                  <tr>
                    <th className="px-4 py-2">Course / Module</th>
                    <th className="px-4 py-2">Date</th>
                    <th className="px-4 py-2">Artifacts</th>
                    <th className="px-4 py-2">Status</th>
                    <th className="px-4 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row) => (
                    <tr key={row.module_id} className="border-b border-outline-variant/60">
                      <td className="px-4 py-3">
                        <div className="text-label-sm text-on-surface-variant">
                          {row.course_title}
                        </div>
                        <div className="font-label-md text-label-md">{row.module_title}</div>
                      </td>
                      <td className="px-4 py-3 text-label-sm text-on-surface-variant">
                        {new Date(row.created_at).toLocaleDateString()}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex gap-1">
                          {row.dots.map((d) => (
                            <StatusDot
                              key={d.type}
                              status={d.status}
                              title={`${d.type}: ${d.status}`}
                            />
                          ))}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <StatusChip status={row.global_status} />
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Link
                          to={`/admin/modules/${row.module_id}/staging`}
                          className="font-label-md text-label-md text-primary underline underline-offset-4"
                        >
                          Open staging
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <div className="flex items-center justify-between">
            <span className="text-label-sm text-on-surface-variant">
              {data.total} module{data.total === 1 ? "" : "s"}
            </span>
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                Prev
              </Button>
              <span className="font-label-sm text-label-sm">
                {page} / {pageCount}
              </span>
              <Button
                variant="secondary"
                size="sm"
                disabled={page >= pageCount}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
