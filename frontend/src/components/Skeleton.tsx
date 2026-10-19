import { cn } from "@/lib/cn";

interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Tailwind height utility, e.g. "h-4". */
  lines?: number;
}

export function Skeleton({ className, lines, ...rest }: SkeletonProps): JSX.Element {
  if (lines && lines > 1) {
    return (
      <div className="flex flex-col gap-2" {...rest}>
        {Array.from({ length: lines }).map((_, i) => (
          <div
            key={i}
            className={cn(
              "h-4 animate-pulse rounded bg-surface-container-highest",
              i === lines - 1 && "w-2/3",
              className,
            )}
          />
        ))}
      </div>
    );
  }
  return (
    <div
      className={cn("h-4 animate-pulse rounded bg-surface-container-highest", className)}
      {...rest}
    />
  );
}
