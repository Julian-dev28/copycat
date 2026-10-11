"use client";

import type { EngineStatus, Settings } from "@/lib/api/types";
import { HL_MIN_ORDER_USD } from "@/lib/api/types";
import { isAccountTooSmall, minMarginForLeverage, settingsLeverage } from "@/lib/copyRecipe";
import { formatUsd } from "@/lib/format";
import { Notice } from "@/components/ui/Notice";

/**
 * Shown when the account can't fund a single Hyperliquid order. Renders
 * nothing while status is loading or equity is unknown.
 */
export function EmptyAccountBanner({ status, settings }: { status?: EngineStatus; settings?: Settings }) {
  if (!status || !isAccountTooSmall(status.equity_usd)) return null;

  const lev = settings ? settingsLeverage(settings) : null;
  const m = settings?.fixed_margin_usd;
  const product = lev && m !== undefined ? m * lev.leverage : null;

  return (
    <Notice tone="warning" title={`Your account has ${formatUsd(status.equity_usd)}. That's not enough to copy anything yet.`}>
      <p>
        Hyperliquid rejects any order under $10. With fixed margin <b className="text-foreground">M</b> at leverage{" "}
        <b className="text-foreground">L</b>, each copy needs{" "}
        <span className="font-num text-foreground">M x L &gt;= {formatUsd(HL_MIN_ORDER_USD)}</span> (the extra 50 cents
        covers rounding), and the margin itself has to fit in your account. Deposit at least a few dollars more before
        turning trading on.
      </p>
      {settings && lev && product !== null && settings.sizing_mode === "fixed_margin" ? (
        <p className="font-num mt-2 text-xs">
          Right now: {formatUsd(m)} x {lev.upperBound ? "up to " : ""}
          {lev.leverage}x = {formatUsd(product)}
          {product >= HL_MIN_ORDER_USD ? " (clears the minimum)" : ` (needs at least ${formatUsd(minMarginForLeverage(lev.leverage))} margin at ${lev.leverage}x)`}
        </p>
      ) : null}
    </Notice>
  );
}
