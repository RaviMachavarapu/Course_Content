import { Icon } from "@/components";

interface AuthShellProps {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}

export function AuthShell({ title, subtitle, children, footer }: AuthShellProps): JSX.Element {
  return (
    <main className="flex min-h-screen items-center justify-center bg-surface p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded bg-tertiary">
            <Icon name="school" filled className="text-[20px] text-white" />
          </div>
          <div className="leading-tight">
            <p className="font-display text-label-md font-extrabold text-primary">Shikshak Dp</p>
            <p className="font-label-sm text-label-sm text-on-surface-variant">Learn</p>
          </div>
        </div>

        <div className="rounded-xl border border-outline-variant bg-surface-container-lowest p-6 shadow-level-1">
          <h1 className="font-headline-md text-headline-md">{title}</h1>
          {subtitle && (
            <p className="mt-1 font-body-md text-body-md text-on-surface-variant">{subtitle}</p>
          )}
          <div className="mt-5">{children}</div>
        </div>

        {footer && (
          <p className="mt-4 text-center font-label-md text-label-md text-on-surface-variant">
            {footer}
          </p>
        )}
      </div>
    </main>
  );
}
