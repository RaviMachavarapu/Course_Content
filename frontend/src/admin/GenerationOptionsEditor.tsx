import { useId } from "react";
import { Icon, Select } from "@/components";
import { cn } from "@/lib/cn";
import type { ArtifactType } from "./api";
import {
  OPTION_FIELDS,
  PROMPT_FIELDS,
  PROMPT_HINT,
  normalizeOptions,
  type OptionField,
  type OptionValues,
} from "./generationOptions";

interface Props {
  type: ArtifactType;
  values: OptionValues;
  onChange: (next: OptionValues) => void;
  /** Omit both to hide the free-text box (e.g. where it isn't editable). */
  prompt?: string;
  onPromptChange?: (next: string) => void;
}

type Choices = OptionField["choices"];

function Segmented({
  label,
  choices,
  value,
  onSelect,
}: {
  label: string;
  choices: Choices;
  value: OptionValues[string];
  onSelect: (v: string) => void;
}): JSX.Element {
  const labelId = useId();
  return (
    <div className="flex flex-col gap-1">
      <span id={labelId} className="font-label-md text-label-md text-on-surface-variant">
        {label}
      </span>
      <div
        role="radiogroup"
        aria-labelledby={labelId}
        className="inline-flex w-fit overflow-hidden rounded-full border border-outline-variant"
      >
        {choices.map((c, i) => {
          const selected = c.value === value;
          return (
            <button
              key={c.value}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => onSelect(c.value)}
              className={cn(
                "flex items-center gap-1 px-3 py-1.5 font-label-md text-label-md transition-colors",
                i > 0 && "border-l border-outline-variant",
                selected
                  ? "bg-primary-container/20 text-primary"
                  : "text-on-surface-variant hover:bg-surface-container-high",
              )}
            >
              {selected && <Icon name="check" className="text-[16px]" />}
              {c.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function Cards({
  label,
  choices,
  value,
  onSelect,
}: {
  label: string;
  choices: Choices;
  value: OptionValues[string];
  onSelect: (v: string) => void;
}): JSX.Element {
  const labelId = useId();
  return (
    <div className="flex flex-col gap-1">
      <span id={labelId} className="font-label-md text-label-md text-on-surface-variant">
        {label}
      </span>
      <div
        role="radiogroup"
        aria-labelledby={labelId}
        className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4"
      >
        {choices.map((c) => {
          const selected = c.value === value;
          return (
            <button
              key={c.value}
              type="button"
              role="radio"
              aria-checked={selected}
              aria-label={c.label}
              onClick={() => onSelect(c.value)}
              className={cn(
                "flex flex-col gap-1 rounded-lg border p-3 text-left transition-colors",
                selected
                  ? "border-primary bg-primary-container/20"
                  : "border-outline-variant hover:bg-surface-container-high",
              )}
            >
              <span className="flex items-center justify-between font-label-md text-label-md text-on-surface">
                {c.label}
                {selected && (
                  <Icon name="check_circle" filled className="text-[16px] text-primary" />
                )}
              </span>
              {c.description && (
                <span className="text-label-sm text-on-surface-variant">{c.description}</span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function Switch({
  field,
  checked,
  onToggle,
}: {
  field: OptionField;
  checked: boolean;
  onToggle: (v: boolean) => void;
}): JSX.Element {
  const descId = useId();
  return (
    <div className="flex w-full items-start justify-between gap-4">
      <div className="flex flex-col gap-1">
        <span className="font-label-md text-label-md text-on-surface">{field.label}</span>
        {field.description && (
          <span id={descId} className="text-label-sm text-on-surface-variant">
            {field.description}
          </span>
        )}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={field.label}
        aria-describedby={field.description ? descId : undefined}
        onClick={() => onToggle(!checked)}
        className={cn(
          "relative h-6 w-11 shrink-0 rounded-full transition-colors",
          checked ? "bg-primary" : "bg-outline-variant",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 h-5 w-5 rounded-full bg-surface-container-lowest transition-transform",
            checked ? "translate-x-5" : "translate-x-0.5",
          )}
        />
      </button>
    </div>
  );
}

/** Per-type generation options plus NotebookLM's free-text box, laid out like
 * NotebookLM's own Studio dialogs — see `generationOptions.ts`. */
export function GenerationOptionsEditor({
  type,
  values,
  onChange,
  prompt,
  onPromptChange,
}: Props): JSX.Element {
  const fields = OPTION_FIELDS[type].filter((f) => !f.visible || f.visible(values));
  const promptField = PROMPT_FIELDS[type];
  const showPrompt =
    promptField && onPromptChange && (!promptField.visible || promptField.visible(values));
  const promptId = useId();
  const set = (key: string, v: OptionValues[string]) =>
    onChange(normalizeOptions(type, { ...values, [key]: v }));

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start gap-x-6 gap-y-4">
        {fields.map((field) => {
          const choices = field.choicesFor ? field.choicesFor(values) : field.choices;
          const value = values[field.key] ?? null;
          if (field.control === "switch")
            return (
              <Switch
                key={field.key}
                field={field}
                checked={value === true}
                onToggle={(v) => set(field.key, v)}
              />
            );
          if (field.control === "cards")
            return (
              <div key={field.key} className="w-full">
                <Cards
                  label={field.label}
                  choices={choices}
                  value={value}
                  onSelect={(v) => set(field.key, v)}
                />
              </div>
            );
          if (field.control === "segmented")
            return (
              <Segmented
                key={field.key}
                label={field.label}
                choices={choices}
                value={value}
                onSelect={(v) => set(field.key, v)}
              />
            );
          return (
            <div key={field.key} className="w-56">
              <Select
                label={field.label}
                value={typeof value === "string" ? value : choices[0]!.value}
                options={choices}
                onChange={(e) => set(field.key, e.target.value)}
              />
            </div>
          );
        })}
      </div>
      {showPrompt && (
        <div className="flex flex-col gap-1">
          <label htmlFor={promptId} className="font-label-md text-label-md text-on-surface-variant">
            {promptField.label}
          </label>
          <textarea
            id={promptId}
            aria-describedby={`${promptId}-hint`}
            rows={3}
            maxLength={4000}
            value={prompt ?? ""}
            placeholder={promptField.placeholder}
            onChange={(e) => onPromptChange(e.target.value)}
            className="rounded-lg border border-outline-variant bg-surface-container-lowest px-3 py-2 text-body-md text-on-surface focus:shadow-focus focus:outline-none"
          />
          <span
            id={`${promptId}-hint`}
            className="font-label-sm text-label-sm text-on-surface-variant"
          >
            {PROMPT_HINT}
          </span>
        </div>
      )}
    </div>
  );
}
