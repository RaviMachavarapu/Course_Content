import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Card, CardBody, ErrorState, Icon, Skeleton } from "@/components";
import { ARTIFACT_LABELS } from "../api";
import { StatusChip } from "../AdminStatus";
import { useInspect } from "../staging/useStaging";
import { ContentView } from "./ContentView";

function MetaRow({ label, value }: { label: string; value: React.ReactNode }): JSX.Element {
  return (
    <div className="flex justify-between gap-4 border-b border-outline-variant/60 py-1.5 last:border-0">
      <span className="font-label-sm text-label-sm text-on-surface-variant">{label}</span>
      <span className="max-w-[60%] truncate text-right font-label-sm text-label-sm">{value}</span>
    </div>
  );
}

export function InspectPage(): JSX.Element {
  const { artifactId = "" } = useParams();
  const [version, setVersion] = useState<string | undefined>(undefined);
  const { data, isPending, isError, refetch } = useInspect(artifactId, version);

  if (isError) {
    return (
      <div className="flex-1 p-4 md:p-margin-desktop">
        <ErrorState title="Could not load this artifact" onRetry={() => void refetch()} />
      </div>
    );
  }

  const v = data?.viewing;
  const moduleId = data?.artifact.module_id;

  return (
    <div className="flex flex-1 flex-col gap-6 p-4 md:p-margin-desktop">
      <div className="flex items-center justify-between gap-3">
        <Link
          to={moduleId ? `/admin/modules/${moduleId}/staging` : "/admin/ingestion"}
          data-testid="btn-ai2"
          className="flex items-center gap-1 font-label-sm text-label-sm text-on-surface-variant hover:text-primary"
        >
          <Icon name="arrow_back" className="text-[16px]" />
          Back to staging
        </Link>
        {data && (
          <div className="flex items-center gap-3">
            <h1 className="font-headline-md text-headline-md">
              {ARTIFACT_LABELS[data.artifact.type]}
            </h1>
            <StatusChip status={data.artifact.status} />
          </div>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_18rem]">
        <Card>
          <CardBody className="p-5">
            {isPending || !v ? (
              <Skeleton lines={8} />
            ) : (
              <ContentView type={data.artifact.type} version={v} />
            )}
          </CardBody>
        </Card>

        <div className="flex flex-col gap-4">
          {data && data.history.length > 0 && (
            <Card>
              <CardBody className="p-4">
                <label className="flex flex-col gap-1 font-label-sm text-label-sm text-on-surface-variant">
                  Version history
                  <select
                    data-testid="btn-ai1"
                    value={version ?? data.history.find((h) => h.is_current)?.id ?? ""}
                    onChange={(e) => setVersion(e.target.value)}
                    className="rounded-lg border border-outline-variant bg-surface-container-lowest px-2 py-1.5 text-body-md"
                  >
                    {data.history.map((h) => (
                      <option key={h.id} value={h.id}>
                        rev {h.revision}
                        {h.is_current ? " (current)" : ""}
                        {h.is_published ? " · published" : ""}
                      </option>
                    ))}
                  </select>
                </label>
              </CardBody>
            </Card>
          )}

          {v && (
            <Card>
              <CardBody className="p-4">
                <p className="mb-2 font-label-md text-label-md font-semibold">Metadata</p>
                <MetaRow label="Revision" value={v.revision} />
                <MetaRow label="Created" value={new Date(v.created_at).toLocaleString()} />
                <MetaRow label="Job id" value={v.generation_job_id ?? "—"} />
                <MetaRow
                  label="Prompt version"
                  value={v.prompt_template_version ?? "Custom prompt (template replaced)"}
                />
                <MetaRow label="Redo note" value={v.redo_note ?? "—"} />
                <MetaRow label="NotebookLM notebook" value={data?.notebooklm_notebook_id ?? "—"} />
                <MetaRow label="NotebookLM artifact" value={v.notebooklm_artifact_id ?? "—"} />
              </CardBody>
            </Card>
          )}

          {v && v.focus_prompt_used && (
            <Card>
              <CardBody className="p-4">
                <p className="mb-2 font-label-md text-label-md font-semibold">focus_prompt used</p>
                <pre className="max-h-64 overflow-auto whitespace-pre-wrap text-label-sm text-on-surface-variant">
                  {v.focus_prompt_used}
                </pre>
              </CardBody>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
