import { forwardRef, useId } from "react";
import { cn } from "@/lib/cn";
import { Icon } from "./Icon";

export interface SelectOption {
  value: string;
  label: string;
}

interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  hint?: string;
  error?: string;
  options: SelectOption[];
  placeholder?: string;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { label, hint, error, options, placeholder, className, id, ...rest },
  ref,
) {
  const autoId = useId();
  const selectId = id ?? autoId;

  return (
    <div className="flex flex-col gap-1">
      {label && (
        <label htmlFor={selectId} className="font-label-md text-label-md text-on-surface-variant">
          {label}
        </label>
      )}
      <div className="relative">
        <select
          ref={ref}
          id={selectId}
          aria-invalid={error ? true : undefined}
          className={cn(
            "w-full appearance-none rounded-lg border bg-surface-container-lowest px-3 py-2 pr-9",
            "text-body-md text-on-surface transition-shadow focus:outline-none focus:shadow-focus",
            error
              ? "border-error focus:border-error"
              : "border-outline-variant focus:border-primary",
            "disabled:opacity-50",
            className,
          )}
          {...rest}
        >
          {placeholder && (
            <option value="" disabled>
              {placeholder}
            </option>
          )}
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <Icon
          name="expand_more"
          className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-on-surface-variant"
        />
      </div>
      {error ? (
        <p className="font-label-sm text-label-sm text-error">{error}</p>
      ) : hint ? (
        <p className="font-label-sm text-label-sm text-on-surface-variant">{hint}</p>
      ) : null}
    </div>
  );
});
