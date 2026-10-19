import { cn } from "@/lib/cn";

interface IconProps {
  /** Material Symbols (Outlined) ligature name, e.g. "check_circle". */
  name: string;
  filled?: boolean;
  className?: string;
  /** Decorative by default; pass a label to expose it to assistive tech. */
  label?: string;
}

export function Icon({ name, filled = false, className, label }: IconProps): JSX.Element {
  return (
    <span
      className={cn("material-symbols-outlined select-none", filled && "is-filled", className)}
      aria-hidden={label ? undefined : true}
      role={label ? "img" : undefined}
      aria-label={label}
    >
      {name}
    </span>
  );
}
