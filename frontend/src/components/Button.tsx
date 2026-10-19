import { forwardRef } from "react";
import { cn } from "@/lib/cn";
import { Icon } from "./Icon";

export type ButtonVariant = "primary" | "secondary" | "student" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Material Symbols name rendered before the label. */
  iconLeft?: string;
  iconRight?: string;
  loading?: boolean;
  fullWidth?: boolean;
}

const base =
  "inline-flex items-center justify-center gap-2 rounded-lg font-label-md text-label-md " +
  "transition-all duration-150 active:scale-[0.98] focus-visible:outline-none " +
  "focus-visible:shadow-focus disabled:pointer-events-none disabled:opacity-50";

const variants: Record<ButtonVariant, string> = {
  primary: "bg-primary text-on-primary hover:bg-primary/90",
  secondary: "border border-primary text-primary bg-transparent hover:bg-primary/5",
  student: "bg-tertiary text-on-tertiary hover:bg-tertiary/90",
  ghost: "text-on-surface-variant hover:bg-surface-container-high",
  danger: "bg-error text-on-error hover:bg-error/90",
};

const sizes: Record<ButtonSize, string> = {
  sm: "px-3 py-1.5",
  md: "px-4 py-2",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "primary",
    size = "md",
    iconLeft,
    iconRight,
    loading = false,
    fullWidth = false,
    className,
    children,
    disabled,
    ...rest
  },
  ref,
) {
  return (
    <button
      ref={ref}
      className={cn(base, variants[variant], sizes[size], fullWidth && "w-full", className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? (
        <Icon name="progress_activity" className="animate-spin text-[18px]" />
      ) : (
        iconLeft && <Icon name={iconLeft} className="text-[18px]" />
      )}
      {children}
      {iconRight && !loading && <Icon name={iconRight} className="text-[18px]" />}
    </button>
  );
});
