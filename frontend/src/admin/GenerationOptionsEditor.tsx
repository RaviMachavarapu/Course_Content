import { Select } from "@/components";
import type { ArtifactType } from "./api";
import { OPTION_FIELDS } from "./generationOptions";

interface Props {
  type: ArtifactType;
  values: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
}

/** Per-type generation options (Language, Quantity/Difficulty, Format/Length,
 * Orientation) mirroring NotebookLM's own Studio UI — see
 * `generationOptions.ts` for the field list per type. */
export function GenerationOptionsEditor({ type, values, onChange }: Props): JSX.Element {
  const fields = OPTION_FIELDS[type];
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {fields.map((field) => (
        <Select
          key={field.key}
          label={field.label}
          value={values[field.key] ?? field.choices[0]!.value}
          options={field.choices}
          onChange={(e) => onChange({ ...values, [field.key]: e.target.value })}
        />
      ))}
    </div>
  );
}
