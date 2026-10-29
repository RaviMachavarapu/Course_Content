import { create } from "zustand";

export type ToastTone = "info" | "success" | "error";

export interface Toast {
  id: string;
  title: string;
  description?: string;
  tone: ToastTone;
}

interface UIState {
  toasts: Toast[];
  sidebarOpen: boolean;
  pushToast: (t: Omit<Toast, "id">) => string;
  dismissToast: (id: string) => void;
  setSidebarOpen: (open: boolean) => void;
}

let toastSeq = 0;

/** `crypto.randomUUID` exists only in secure contexts (https, localhost): on a
 * plain-http LAN address it is undefined and every toast would throw. */
export function newToastId(): string {
  const c = globalThis.crypto as Crypto | undefined;
  if (typeof c?.randomUUID === "function") return c.randomUUID();
  toastSeq += 1;
  return `toast-${Date.now().toString(36)}-${toastSeq}-${Math.random().toString(36).slice(2, 8)}`;
}

export const useUIStore = create<UIState>((set) => ({
  toasts: [],
  sidebarOpen: false,
  pushToast: (t) => {
    const id = newToastId();
    set((s) => ({ toasts: [...s.toasts, { ...t, id }] }));
    return id;
  },
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })),
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
}));

/** Ergonomic hook for firing toasts from anywhere. */
export function useToast(): {
  toast: (t: Omit<Toast, "id" | "tone"> & { tone?: ToastTone }) => string;
  dismiss: (id: string) => void;
} {
  const push = useUIStore((s) => s.pushToast);
  const dismiss = useUIStore((s) => s.dismissToast);
  return {
    toast: ({ tone = "info", ...rest }) => push({ tone, ...rest }),
    dismiss,
  };
}
