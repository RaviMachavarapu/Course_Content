import { forwardRef, useId } from "react";
import { cn } from "@/lib/cn";

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  hint?: string;
  error?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, hint, error, className, id, ...rest },
  ref,
) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const describedBy = error ? `${inputId}-err` : hint ? `${inputId}-hint` : undefined;

  return (
    <div className="flex flex-col gap-1">
      {label && (
        <label htmlFor={inputId} className="font-label-md text-label-md text-on-surface-variant">
          {label}
        </label>
      )}
      <input
        ref={ref}
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={cn(
          "rounded-lg border bg-surface-container-lowest px-3 py-2 text-body-md text-on-surface",
          "placeholder:text-outline transition-shadow focus:outline-none focus:shadow-focus",
          error ? "border-error focus:border-error" : "border-outline-variant focus:border-primary",
          "disabled:opacity-50",
          className,
        )}
        {...rest}
      />
      {error ? (
        <p id={`${inputId}-err`} className="font-label-sm text-label-sm text-error">
          {error}
        </p>
      ) : hint ? (
        <p id={`${inputId}-hint`} className="font-label-sm text-label-sm text-on-surface-variant">
          {hint}
        </p>
      ) : null}
    </div>
  );
});
