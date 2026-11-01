import { useState } from "react";
import { Button, Modal } from "@/components";
import type { ArtifactType } from "../api";
import { GenerationOptionsEditor } from "../GenerationOptionsEditor";
import {
  DEFAULT_OPTIONS,
  normalizeOptions,
  optionsProblem,
  type OptionValues,
} from "../generationOptions";

interface RedoModalProps {
  open: boolean;
  type: ArtifactType;
  typeLabel: string;
  pending: boolean;
  initialOptions: OptionValues;
  /** The artifact's stored custom prompt ("" = it uses the Settings template). */
  initialPrompt: string;
  onCancel: () => void;
  onStart: (note: string | null, options: OptionValues, customPrompt: string) => void;
}

export function RedoModal({
  open,
  type,
  typeLabel,
  pending,
  initialOptions,
  initialPrompt,
  onCancel,
  onStart,
}: RedoModalProps): JSX.Element {
  const [note, setNote] = useState("");
  // Stored options can predate newer fields: start from NotebookLM's defaults.
  const [options, setOptions] = useState<OptionValues>(
    normalizeOptions(type, { ...DEFAULT_OPTIONS[type], ...initialOptions }),
  );
  const problem = optionsProblem(type, options);
  // Whatever is in this box is sent (owner decision 2026-10-20); empty means
  // "use the Settings template".
  const [customPrompt, setCustomPrompt] = useState(initialPrompt);

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
            disabled={problem !== null}
            onClick={() => onStart(note.trim() || null, options, customPrompt.trim())}
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
          <GenerationOptionsEditor
            type={type}
            values={options}
            onChange={setOptions}
            prompt={customPrompt}
            onPromptChange={setCustomPrompt}
          />
          {problem && (
            <p role="alert" className="mt-2 font-label-sm text-label-sm text-error">
              {problem}
            </p>
          )}
        </div>
      </div>
    </Modal>
  );
}
