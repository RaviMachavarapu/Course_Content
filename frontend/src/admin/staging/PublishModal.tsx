import { Button, Icon, Modal } from "@/components";
import { ARTIFACT_LABELS } from "../api";
import type { StagingArtifact } from "./api";

const SKIP_REASON: Record<string, string> = {
  pending: "not generated yet",
  draft: "not generated yet",
  processing: "still generating",
  error: "generation failed",
  published: "already published",
};

interface Props {
  open: boolean;
  scope: "module" | "course";
  artifacts: StagingArtifact[];
  pending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export function PublishModal({
  open,
  scope,
  artifacts,
  pending,
  onCancel,
  onConfirm,
}: Props): JSX.Element {
  const willPublish = artifacts.filter((a) => a.status === "ready");
  const skipped = artifacts.filter((a) => a.status !== "ready" && a.status !== "published");

  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={scope === "course" ? "Publish complete course" : "Publish module"}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            loading={pending}
            disabled={willPublish.length === 0}
            onClick={onConfirm}
            data-testid="btn-publish-confirm"
          >
            Publish {willPublish.length} artifact{willPublish.length === 1 ? "" : "s"}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4 text-body-md">
        <div>
          <p className="mb-1 font-label-md text-label-md font-semibold text-secondary">
            Will publish ({willPublish.length})
          </p>
          {willPublish.length ? (
            <ul className="flex flex-col gap-1">
              {willPublish.map((a) => (
                <li key={a.id} className="flex items-center gap-2">
                  <Icon name="check_circle" filled className="text-[16px] text-secondary" />
                  {ARTIFACT_LABELS[a.type]}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-on-surface-variant">Nothing is ready to publish yet.</p>
          )}
        </div>

        {skipped.length > 0 && (
          <div>
            <p className="mb-1 font-label-md text-label-md font-semibold text-on-surface-variant">
              Skipped ({skipped.length})
            </p>
            <ul className="flex flex-col gap-1">
              {skipped.map((a) => (
                <li key={a.id} className="flex items-center gap-2 text-on-surface-variant">
                  <Icon name="remove_circle_outline" className="text-[16px]" />
                  {ARTIFACT_LABELS[a.type]}
                  <span className="text-label-sm text-outline">
                    — {SKIP_REASON[a.status] ?? a.status}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Modal>
  );
}
