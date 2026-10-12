"use client";

import Link from "next/link";
import { useSyncExternalStore } from "react";
import { Telescope, X } from "lucide-react";

const STEPS = [
  { n: 1, title: "Pick a trader", text: "Each trader is a market. Their index tracks how their trading did, with deposits and withdrawals removed." },
  { n: 2, title: "Invest $ with your leverage", text: "Follow their leverage, or set yours. The preview shows exactly which of their positions you'd hold." },
  { n: 3, title: "Watch it in Your copies", text: "copycat mirrors every trade they make. Adjust the size any time, or stop and close." },
];

const KEY = "copycat.trade.explainer.dismissed";
const EVENT = "copycat:explainer";

function read(): boolean {
  try {
    return window.localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

function subscribe(cb: () => void) {
  window.addEventListener(EVENT, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(EVENT, cb);
    window.removeEventListener("storage", cb);
  };
}

function dismiss() {
  try {
    window.localStorage.setItem(KEY, "1");
  } catch {
    // storage blocked: it hides for this page view only
  }
  window.dispatchEvent(new Event(EVENT));
}

/** First-run strip (DESIGN 6 Trade): what this page does in three steps, plus Scout. Dismissible, remembered per browser. */
export function Explainer({ scoutHref }: { scoutHref: string }) {
  // SSR renders it hidden so a dismissed strip never flashes.
  const dismissed = useSyncExternalStore(subscribe, read, () => true);
  if (dismissed) return null;
  return (
    <section aria-label="How Trade works" className="relative flex flex-col gap-3 rounded-xl border border-border bg-surface p-4 pr-10 shadow-e1 md:flex-row md:items-center">
      <ol className="grid flex-1 gap-3 sm:grid-cols-3">
        {STEPS.map((s, i) => (
          <li key={s.n} className={i > 0 ? "hidden gap-2.5 sm:flex" : "flex gap-2.5"}>
            <span className="num-sm flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full border border-border bg-surface-2 text-fg-soft">{s.n}</span>
            <span>
              <span className="block text-sm font-medium text-fg">{s.title}</span>
              <span className="block text-xs text-muted">{s.text}</span>
            </span>
          </li>
        ))}
      </ol>
      <Link
        href={scoutHref}
        className="inline-flex items-center gap-1.5 self-start whitespace-nowrap rounded-full border border-border bg-surface-2 px-3 py-1.5 text-xs font-medium text-fg-soft transition-colors hover:border-border-strong hover:text-fg md:self-center"
      >
        <Telescope size={14} aria-hidden="true" /> Research traders in Scout
      </Link>
      <button
        type="button"
        onClick={dismiss}
        aria-label="Dismiss the intro"
        className="absolute top-2 right-2 grid h-7 w-7 place-items-center rounded-full text-muted transition-colors hover:bg-surface-2 hover:text-fg"
      >
        <X size={14} aria-hidden="true" />
      </button>
    </section>
  );
}
