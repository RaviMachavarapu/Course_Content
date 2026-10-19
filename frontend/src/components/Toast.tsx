import { useEffect } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/cn";
import { type Toast as ToastModel, type ToastTone, useUIStore } from "@/lib/store";
import { Icon } from "./Icon";

const tone: Record<ToastTone, { icon: string; className: string }> = {
  info: { icon: "info", className: "border-outline-variant" },
  success: { icon: "check_circle", className: "border-secondary" },
  error: { icon: "error", className: "border-error" },
};

const AUTO_DISMISS_MS = 5000;

function ToastCard({ toast }: { toast: ToastModel }): JSX.Element {
  const dismiss = useUIStore((s) => s.dismissToast);
  useEffect(() => {
    const t = setTimeout(() => dismiss(toast.id), AUTO_DISMISS_MS);
    return () => clearTimeout(t);
  }, [toast.id, dismiss]);

  const t = tone[toast.tone];
  return (
    <div
      role="status"
      className={cn(
        "pointer-events-auto flex w-80 items-start gap-3 rounded-lg border-l-4 bg-surface-container-lowest",
        "px-4 py-3 shadow-level-2",
        t.className,
      )}
    >
      <Icon name={t.icon} filled className="mt-0.5 text-primary" />
      <div className="flex-1">
        <p className="font-label-md text-label-md font-semibold">{toast.title}</p>
        {toast.description && (
          <p className="font-label-sm text-label-sm text-on-surface-variant">{toast.description}</p>
        )}
      </div>
      <button
        onClick={() => dismiss(toast.id)}
        aria-label="Dismiss notification"
        className="rounded-full p-0.5 text-on-surface-variant hover:bg-surface-container-high"
      >
        <Icon name="close" className="text-[18px]" />
      </button>
    </div>
  );
}

/** Mount once near the app root. */
export function Toaster(): JSX.Element | null {
  const toasts = useUIStore((s) => s.toasts);
  if (typeof document === "undefined") return null;
  return createPortal(
    <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex flex-col gap-2">
      {toasts.map((t) => (
        <ToastCard key={t.id} toast={t} />
      ))}
    </div>,
    document.body,
  );
}
