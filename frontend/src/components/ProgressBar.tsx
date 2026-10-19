import { cn } from "@/lib/cn";

interface ProgressBarProps {
  /** 0–100. */
  value: number;
  /**
   * "active" — violet (in-progress, student).
   * "complete" — emerald (finished segments).
   */
  tone?: "active" | "complete";
  showLabel?: boolean;
  className?: string;
}

export function ProgressBar({
  value,
  tone = "active",
  showLabel = false,
  className,
}: ProgressBarProps): JSX.Element {
  const pct = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        className="h-2 flex-1 overflow-hidden rounded-full bg-surface-container-highest"
      >
        <div
          className={cn(
            "h-full rounded-full transition-[width] duration-300",
            tone === "complete" ? "bg-secondary" : "bg-tertiary",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      {showLabel && (
        <span className="font-label-sm text-label-sm tabular-nums text-on-surface-variant">
          {pct}%
        </span>
      )}
    </div>
  );
}
