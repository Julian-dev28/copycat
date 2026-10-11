import Link from "next/link";
import { FlaskConical, PauseCircle } from "lucide-react";
import type { TradeSettings } from "@/lib/trade/types";

/** Trading off -> "paused"; dry run -> what that means. So nobody wonders why nothing trades. */
export function TicketBanners({ settings, settingsHref }: { settings: TradeSettings | undefined; settingsHref: string }) {
  if (settings && !settings.enabled) {
    return (
      <p className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-xs">
        <PauseCircle size={14} className="mt-0.5 flex-shrink-0 text-warning" aria-hidden="true" />
        <span>
          Copying is paused: <Link href={settingsHref} className="font-medium text-accent hover:underline">enable it in Settings</Link>. You can still set up
          wallets; nothing trades until then.
        </span>
      </p>
    );
  }
  if (settings?.dry_run) {
    return (
      <p className="flex items-start gap-2 rounded-lg border border-accent/30 bg-accent-soft px-3 py-2 text-xs">
        <FlaskConical size={14} className="mt-0.5 flex-shrink-0 text-accent" aria-hidden="true" />
        <span>
          Dry run: copycat logs what it would do and places no orders. Turn it off in{" "}
          <Link href={settingsHref} className="font-medium text-accent hover:underline">Settings</Link>.
        </span>
      </p>
    );
  }
  return null;
}
