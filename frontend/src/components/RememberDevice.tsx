import { useId } from "react";

/** "Remember this device" on the sign-in pages (ticked by default): only then
 * does the browser keep the trusted-device cookie that lets its owner past
 * delays caused by someone else's wrong guesses. Untick on a shared computer. */
export function RememberDevice({
  checked,
  onChange,
  testid,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  testid?: string;
}): JSX.Element {
  const id = useId();
  const hintId = `${id}-hint`;
  return (
    <div className="flex items-start gap-2">
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        aria-describedby={hintId}
        data-testid={testid}
        className="mt-0.5 h-4 w-4 accent-primary"
      />
      <div className="flex flex-col">
        <label htmlFor={id} className="font-label-md text-label-md text-on-surface">
          Remember this device
        </label>
        <span id={hintId} className="font-label-sm text-label-sm text-on-surface-variant">
          Untick on a shared or public computer.
        </span>
      </div>
    </div>
  );
}
