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

export const useUIStore = create<UIState>((set) => ({
  toasts: [],
  sidebarOpen: false,
  pushToast: (t) => {
    const id = crypto.randomUUID();
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
