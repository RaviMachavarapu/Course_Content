import { Link } from "react-router-dom";
import { cn } from "@/lib/cn";
import { useUIStore } from "@/lib/store";
import { Icon } from "./Icon";

interface TopBarProps {
  title: string;
  backTo?: string;
  backLabel?: string;
  /** Right-aligned content (status chip, actions, progress…). */
  right?: React.ReactNode;
  /** Compact "Focus Bar" styling for the student workspace. */
  focus?: boolean;
  className?: string;
}

export function TopBar({
  title,
  backTo,
  backLabel = "Back",
  right,
  focus = false,
  className,
}: TopBarProps): JSX.Element {
  const setSidebarOpen = useUIStore((s) => s.setSidebarOpen);

  return (
    <header
      className={cn(
        "sticky top-0 z-30 flex items-center justify-between gap-4 border-b border-outline-variant",
        "bg-surface-container-lowest px-4 md:px-margin-desktop",
        focus ? "py-2" : "py-md",
        className,
      )}
    >
      <div className="flex min-w-0 items-center gap-3">
        {!focus && (
          <button
            aria-label="Open menu"
            className="rounded-lg p-1 text-on-surface-variant hover:bg-surface-container-high lg:hidden"
            onClick={() => setSidebarOpen(true)}
          >
            <Icon name="menu" />
          </button>
        )}
        <div className="flex min-w-0 flex-col">
          {backTo && (
            <Link
              to={backTo}
              className="flex w-fit items-center gap-1 font-label-sm text-label-sm text-on-surface-variant transition-colors hover:text-primary"
            >
              <Icon name="arrow_back" className="text-[16px]" />
              {backLabel}
            </Link>
          )}
          <h1
            className={cn(
              "truncate text-on-background",
              focus
                ? "font-label-md text-label-md font-semibold"
                : "font-headline-md text-headline-md",
            )}
          >
            {title}
          </h1>
        </div>
      </div>
      {right && <div className="flex shrink-0 items-center gap-3">{right}</div>}
    </header>
  );
}
