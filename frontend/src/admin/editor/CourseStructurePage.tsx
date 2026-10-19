import { useCallback, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Button, ErrorState, Icon, Input, Modal, Skeleton } from "@/components";
import { ApiError } from "@/lib/api";
import { useToast } from "@/lib/store";
import type { ModuleSummary } from "../api";
import { ModuleRow } from "./ModuleRow";
import { useCourseStructure, useModuleOps } from "./useEditor";

export function CourseStructurePage(): JSX.Element {
  const { courseId = "" } = useParams();
  const navigate = useNavigate();
  const { toast } = useToast();
  const { data: course, isPending, isError, refetch } = useCourseStructure(courseId);
  const ops = useModuleOps(courseId);

  const [renaming, setRenaming] = useState<ModuleSummary | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [deleting, setDeleting] = useState<ModuleSummary | null>(null);

  const busy = ops.move.isPending || ops.regenerate.isPending || ops.remove.isPending;

  // stable identities so <Modal>'s focus/scroll effect doesn't re-run per keystroke
  const closeRename = useCallback(() => setRenaming(null), []);
  const closeDelete = useCallback(() => setDeleting(null), []);

  if (isError) {
    return (
      <div className="flex-1 p-4 md:p-margin-desktop">
        <ErrorState title="Could not load course" onRetry={() => void refetch()} />
      </div>
    );
  }

  const modules = [...(course?.modules ?? [])].sort((a, b) => a.order_index - b.order_index);

  return (
    <div className="flex flex-1 flex-col gap-6 p-4 md:p-margin-desktop">
      <div className="flex flex-col gap-2">
        <nav className="flex items-center gap-1 font-label-sm text-label-sm text-on-surface-variant">
          <Link to="/admin/editor" className="hover:text-primary">
            Course Editor
          </Link>
          <Icon name="chevron_right" className="text-[16px]" />
          <span>Structure</span>
        </nav>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="font-headline-lg text-headline-lg text-on-background">
            {course?.title ?? <Skeleton className="h-7 w-56" />}
          </h1>
          <Button
            iconLeft="add"
            data-testid="btn-ce1"
            onClick={() => navigate(`/admin/ingestion?course=${courseId}`)}
          >
            Add New Video Source
          </Button>
        </div>
      </div>

      {isPending ? (
        <div className="grid gap-3">
          {[0, 1].map((i) => (
            <Skeleton key={i} className="h-40" />
          ))}
        </div>
      ) : modules.length === 0 ? (
        <p className="rounded-xl border border-dashed border-outline-variant bg-surface-container-low px-6 py-12 text-center text-on-surface-variant">
          No modules yet. Use “Add New Video Source”.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {modules.map((m, i) => (
            <ModuleRow
              key={m.id}
              module={m}
              index={i}
              isFirst={i === 0}
              isLast={i === modules.length - 1}
              busy={busy}
              onRename={() => {
                setRenaming(m);
                setRenameValue(m.title);
              }}
              onMove={(direction) =>
                ops.move.mutate(
                  { moduleId: m.id, direction },
                  {
                    onError: (err) =>
                      toast({
                        title: "Could not reorder",
                        description: err instanceof ApiError ? err.message : undefined,
                        tone: "error",
                      }),
                  },
                )
              }
              onRegenerate={() =>
                ops.regenerate.mutate(m.id, {
                  onSuccess: (res) =>
                    toast({
                      title: "Re-run started",
                      description: `${res.job_ids.length} artifacts regenerating`,
                      tone: "success",
                    }),
                  onError: (err) =>
                    toast({
                      title: "Could not re-run",
                      description: err instanceof ApiError ? err.message : undefined,
                      tone: "error",
                    }),
                })
              }
              onDelete={() => setDeleting(m)}
            />
          ))}
        </div>
      )}

      <Modal
        open={renaming !== null}
        onClose={closeRename}
        title="Rename module"
        footer={
          <>
            <Button variant="ghost" onClick={() => setRenaming(null)}>
              Cancel
            </Button>
            <Button
              data-testid="btn-ce4-confirm"
              loading={ops.rename.isPending}
              disabled={!renameValue.trim()}
              onClick={() => {
                if (!renaming) return;
                ops.rename.mutate(
                  { moduleId: renaming.id, title: renameValue.trim() },
                  {
                    onSuccess: () => {
                      setRenaming(null);
                      toast({ title: "Module renamed", tone: "success" });
                    },
                    onError: (err) =>
                      toast({
                        title: "Rename failed",
                        description: err instanceof ApiError ? err.message : undefined,
                        tone: "error",
                      }),
                  },
                );
              }}
            >
              Save
            </Button>
          </>
        }
      >
        <Input
          label="Module title"
          value={renameValue}
          onChange={(e) => setRenameValue(e.target.value)}
        />
      </Modal>

      <Modal
        open={deleting !== null}
        onClose={closeDelete}
        title="Delete module"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeleting(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              data-testid="btn-ce8-confirm"
              loading={ops.remove.isPending}
              onClick={() => {
                if (!deleting) return;
                ops.remove.mutate(deleting.id, {
                  onSuccess: () => {
                    setDeleting(null);
                    toast({ title: "Module deleted", tone: "success" });
                  },
                  onError: (err) =>
                    toast({
                      title: "Delete failed",
                      description: err instanceof ApiError ? err.message : undefined,
                      tone: "error",
                    }),
                });
              }}
            >
              Delete permanently
            </Button>
          </>
        }
      >
        <p>
          This permanently removes <strong>{deleting?.title}</strong>, all six artifacts, every
          version, generated media, and any published content students can currently see. This
          cannot be undone.
        </p>
      </Modal>
    </div>
  );
}
