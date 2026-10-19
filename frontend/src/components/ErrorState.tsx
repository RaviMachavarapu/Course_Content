import { cn } from "@/lib/cn";
import { Button } from "./Button";
import { Icon } from "./Icon";

interface ErrorStateProps {
  title?: string;
  description?: string;
  onRetry?: () => void;
  className?: string;
}

export function ErrorState({
  title = "Something went wrong",
  description = "The request failed. Try again in a moment.",
  onRetry,
  className,
}: ErrorStateProps): JSX.Element {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-xl border border-error/30",
        "bg-error-container/40 px-6 py-12 text-center",
        className,
      )}
    >
      <Icon name="error" filled className="text-[40px] text-error" />
      <p className="font-headline-md text-headline-md text-on-error-container">{title}</p>
      <p className="max-w-sm font-body-md text-body-md text-on-surface-variant">{description}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" iconLeft="refresh" onClick={onRetry} className="mt-2">
          Retry
        </Button>
      )}
    </div>
  );
}
