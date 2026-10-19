import { useEffect, useState } from "react";
import { Button, Card, CardBody, ErrorState, Skeleton } from "@/components";
import { ApiError } from "@/lib/api";
import { useToast } from "@/lib/store";
import { ARTIFACT_LABELS, ARTIFACT_TYPES } from "../api";
import type { PromptTemplate } from "./api";
import { usePromptMutations, usePrompts } from "./useSettings";

function PromptCard({ template }: { template: PromptTemplate }): JSX.Element {
  const type = template.artifact_type;
  const { save, restore } = usePromptMutations();
  const { toast } = useToast();
  const [draft, setDraft] = useState(template.body);
  const [confirmRestore, setConfirmRestore] = useState(false);

  // re-sync when a save/restore produces a new active version
  useEffect(() => setDraft(template.body), [template.body, template.version]);

  const dirty = draft.trim() !== template.body.trim();
  const busy = save.isPending || restore.isPending;

  return (
    <Card>
      <CardBody className="flex flex-col gap-3 p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-headline-md text-headline-md">{ARTIFACT_LABELS[type]}</h3>
          <span className="font-label-sm text-label-sm text-on-surface-variant">
            v{template.version} · updated {new Date(template.updated_at).toLocaleString()}
          </span>
        </div>
        <textarea
          aria-label={`${ARTIFACT_LABELS[type]} prompt`}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={8}
          className="w-full rounded-lg border border-outline-variant bg-surface-container-lowest p-3 font-mono text-body-sm text-on-surface focus:border-primary focus:outline-none focus:shadow-focus"
        />
        <div className="flex flex-wrap gap-2">
          <Button
            data-testid={`btn-st1-${type}`}
            loading={save.isPending}
            disabled={!dirty || !draft.trim() || busy}
            onClick={() =>
              save.mutate(
                { type, body: draft },
                {
                  onSuccess: (t) => toast({ title: `${ARTIFACT_LABELS[type]} saved as v${t.version}`, tone: "success" }),
                  onError: (err) =>
                    toast({
                      title: "Save failed",
                      description: err instanceof ApiError ? err.message : undefined,
                      tone: "error",
                    }),
                },
              )
            }
          >
            Save
          </Button>
          {confirmRestore ? (
            <>
              <Button
                variant="danger"
                data-testid={`btn-st2-${type}-confirm`}
                loading={restore.isPending}
                onClick={() =>
                  restore.mutate(type, {
                    onSuccess: () => {
                      setConfirmRestore(false);
                      toast({ title: `${ARTIFACT_LABELS[type]} restored to default`, tone: "success" });
                    },
                  })
                }
              >
                Confirm restore
              </Button>
              <Button variant="ghost" onClick={() => setConfirmRestore(false)}>
                Cancel
              </Button>
            </>
          ) : (
            <Button
              variant="secondary"
              data-testid={`btn-st2-${type}`}
              disabled={busy}
              onClick={() => setConfirmRestore(true)}
            >
              Restore default
            </Button>
          )}
          {dirty && (
            <span className="self-center font-label-sm text-label-sm text-tertiary">
              Unsaved changes
            </span>
          )}
        </div>
      </CardBody>
    </Card>
  );
}

export function PromptsTab(): JSX.Element {
  const { data, isPending, isError, refetch } = usePrompts();

  if (isError) return <ErrorState title="Could not load prompts" onRetry={() => void refetch()} />;

  const byType = new Map((data ?? []).map((t) => [t.artifact_type, t]));

  return (
    <div className="flex flex-col gap-4">
      <p className="text-body-md text-on-surface-variant">
        Each save creates a new active version. Generations and redos from then on use the new
        text; past versions record the version they ran with.
      </p>
      {isPending
        ? ARTIFACT_TYPES.map((t) => <Skeleton key={t} className="h-64" />)
        : ARTIFACT_TYPES.map((t) => {
            const tpl = byType.get(t);
            return tpl ? <PromptCard key={t} template={tpl} /> : null;
          })}
    </div>
  );
}
