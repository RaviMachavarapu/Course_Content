import { cn } from "@/lib/cn";
import { Icon } from "./Icon";

export type ChipStatus = "processing" | "ready" | "error" | "published" | "pending";

interface ChipProps {
  status: ChipStatus;
  /** Override the default label for the status. */
  children?: React.ReactNode;
  className?: string;
}

const config: Record<
  ChipStatus,
  { label: string; className: string; icon: string; spin?: boolean; filled?: boolean }
> = {
  processing: {
    label: "Processing",
    className: "bg-tertiary-fixed text-on-tertiary-fixed-variant",
    icon: "progress_activity",
    spin: true,
  },
  ready: {
    label: "Ready",
    className: "bg-secondary-container text-on-secondary-container",
    icon: "check_circle",
    filled: true,
  },
  error: {
    label: "Error",
    className: "bg-error-container text-on-error-container",
    icon: "error",
    filled: true,
  },
  published: {
    label: "Published",
    className: "bg-primary text-on-primary",
    icon: "public",
    filled: true,
  },
  pending: {
    label: "Pending Review",
    className: "bg-warning-container text-warning border border-warning-outline",
    icon: "schedule",
  },
};

export function Chip({ status, children, className }: ChipProps): JSX.Element {
  const c = config[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5",
        "font-label-sm text-label-sm uppercase tracking-wide",
        c.className,
        className,
      )}
      data-status={status}
    >
      <Icon
        name={c.icon}
        filled={c.filled}
        className={cn("text-[12px]", c.spin && "animate-spin")}
      />
      {children ?? c.label}
    </span>
  );
}
