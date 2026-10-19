import { useState } from "react";
import { Button, Modal } from "@/components";
import type { ArtifactType } from "../api";
import { GenerationOptionsEditor } from "../GenerationOptionsEditor";
import { DEFAULT_OPTIONS } from "../generationOptions";

interface RedoModalProps {
  open: boolean;
  type: ArtifactType;
  typeLabel: string;
  pending: boolean;
  initialOptions: Record<string, string>;
  onCancel: () => void;
  onStart: (note: string | null, options: Record<string, string>) => void;
}

export function RedoModal({
  open,
  type,
  typeLabel,
  pending,
  initialOptions,
  onCancel,
  onStart,
}: RedoModalProps): JSX.Element {
  const [note, setNote] = useState("");
  const [options, setOptions] = useState<Record<string, string>>(
    Object.keys(initialOptions).length ? initialOptions : DEFAULT_OPTIONS[type],
  );

  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={`Redo ${typeLabel}`}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel} data-testid="btn-sr8">
            Cancel
          </Button>
          <Button
            loading={pending}
            onClick={() => onStart(note.trim() || null, options)}
            data-testid="btn-sr7"
          >
            Start regeneration
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <label className="flex flex-col gap-1 font-label-md text-label-md text-on-surface-variant">
          Instruction (optional) — what should change?
          <textarea
            rows={4}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="rounded-lg border border-outline-variant bg-surface-container-lowest px-3 py-2 text-body-md text-on-surface focus:shadow-focus focus:outline-none"
          />
        </label>
        <div data-testid="redo-options">
          <p className="mb-1 font-label-md text-label-md text-on-surface-variant">Options</p>
          <GenerationOptionsEditor type={type} values={options} onChange={setOptions} />
        </div>
      </div>
    </Modal>
  );
}
