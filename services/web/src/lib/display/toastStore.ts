/**
 * Toast queue (DESIGN 5 Toasts): newest last, at most MAX visible, auto
 * dismiss after 5s, paused while hovered or focused. A plain store so any
 * code can call `toast(...)`; <Toaster> renders it. Timers are explicit
 * (start/pause) so the logic is testable with fake timers.
 */

export type ToastTone = "info" | "success" | "error";

export interface Toast {
  id: number;
  tone: ToastTone;
  message: string;
  action?: { label: string; onClick: () => void };
  /** ms; 0 keeps it until dismissed. */
  duration: number;
}

export const TOAST_DURATION_MS = 5000;
export const TOAST_MAX = 3;

type Listener = () => void;

export function createToastStore(clock: { set: typeof setTimeout; clear: typeof clearTimeout } = { set: setTimeout, clear: clearTimeout }) {
  let items: Toast[] = [];
  let nextId = 1;
  const timers = new Map<number, { handle: ReturnType<typeof setTimeout> | null; remaining: number; startedAt: number }>();
  const listeners = new Set<Listener>();
  const emit = () => listeners.forEach((l) => l());

  function arm(id: number, ms: number) {
    if (ms <= 0) return;
    const handle = clock.set(() => dismiss(id), ms);
    timers.set(id, { handle, remaining: ms, startedAt: Date.now() });
  }

  function show(t: Omit<Toast, "id" | "duration"> & { duration?: number }): number {
    const id = nextId++;
    const duration = t.duration ?? (t.tone === "error" ? TOAST_DURATION_MS * 2 : TOAST_DURATION_MS);
    items = [...items, { ...t, id, duration }];
    while (items.length > TOAST_MAX) dismiss(items[0].id, false);
    arm(id, duration);
    emit();
    return id;
  }

  function dismiss(id: number, notify = true) {
    const tm = timers.get(id);
    if (tm?.handle) clock.clear(tm.handle);
    timers.delete(id);
    const before = items.length;
    items = items.filter((t) => t.id !== id);
    if (notify && items.length !== before) emit();
  }

  /** Hover/focus: stop the clock, remember what is left. */
  function pause(id: number) {
    const tm = timers.get(id);
    if (!tm?.handle) return;
    clock.clear(tm.handle);
    timers.set(id, { handle: null, remaining: Math.max(0, tm.remaining - (Date.now() - tm.startedAt)), startedAt: 0 });
  }

  function resume(id: number) {
    const tm = timers.get(id);
    if (!tm || tm.handle) return;
    arm(id, Math.max(1000, tm.remaining));
  }

  return {
    show,
    dismiss: (id: number) => dismiss(id),
    pause,
    resume,
    get: () => items,
    subscribe(l: Listener) {
      listeners.add(l);
      return () => listeners.delete(l);
    },
  };
}

export type ToastStore = ReturnType<typeof createToastStore>;

/** The app's store. */
export const toasts = createToastStore();

/** toast("Settings saved") / toast.error("Couldn't stop copying") */
export const toast = Object.assign((message: string, opts: Partial<Omit<Toast, "id" | "message">> = {}) => toasts.show({ tone: "info", message, ...opts }), {
  success: (message: string, opts: Partial<Omit<Toast, "id" | "message" | "tone">> = {}) => toasts.show({ tone: "success", message, ...opts }),
  error: (message: string, opts: Partial<Omit<Toast, "id" | "message" | "tone">> = {}) => toasts.show({ tone: "error", message, ...opts }),
});
