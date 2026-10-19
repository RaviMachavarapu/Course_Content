import { cn } from "@/lib/cn";
import { Icon } from "./Icon";

interface EmptyStateProps {
  icon?: string;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({
  icon = "inbox",
  title,
  description,
  action,
  className,
}: EmptyStateProps): JSX.Element {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed",
        "border-outline-variant bg-surface-container-low px-6 py-12 text-center",
        className,
      )}
    >
      <Icon name={icon} className="text-[40px] text-outline" />
      <p className="font-headline-md text-headline-md">{title}</p>
      {description && (
        <p className="max-w-sm font-body-md text-body-md text-on-surface-variant">{description}</p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
