import Link from "next/link";
import { Telescope } from "lucide-react";

const STEPS = [
  { n: 1, title: "Pick a wallet", text: "Each wallet is a market. Its index tracks how its trading did, with deposits and withdrawals removed." },
  { n: 2, title: "Invest $ with your leverage", text: "Follow their leverage, or set yours. The preview shows exactly which of their positions you'd hold." },
  { n: 3, title: "Watch it in Your wallets", text: "copycat mirrors every trade they make. Adjust the size any time, or stop and close." },
];

/** First-run card: what this page does, in three steps, plus a pointer to Scout. */
export function Explainer({ scoutHref }: { scoutHref: string }) {
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-accent/30 bg-accent-soft/40 p-4 md:flex-row md:items-center">
      <ol className="grid flex-1 gap-3 sm:grid-cols-3">
        {STEPS.map((s) => (
          <li key={s.n} className="flex gap-2.5">
            <span className="font-num flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-accent text-xs font-bold text-accent-foreground">{s.n}</span>
            <span>
              <span className="block text-sm font-semibold">{s.title}</span>
              <span className="block text-xs text-muted">{s.text}</span>
            </span>
          </li>
        ))}
      </ol>
      <Link href={scoutHref} className="inline-flex items-center gap-1.5 self-start whitespace-nowrap rounded-lg border border-border bg-surface px-3 py-2 text-xs font-medium hover:text-accent md:self-center">
        <Telescope size={14} aria-hidden="true" /> Research wallets in Scout
      </Link>
    </div>
  );
}
