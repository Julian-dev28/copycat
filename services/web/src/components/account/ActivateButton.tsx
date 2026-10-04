"use client";

import { Zap } from "lucide-react";
import Link from "next/link";
import { Button, type ButtonProps } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { accountErrorText, isOpenCopiesConflict } from "@/lib/account/errors";
import { closeWalletManager } from "@/lib/account/managerStore";
import type { TradingAccount } from "@/lib/account/types";
import { ErrorLine } from "./bits";
import { useAccountMode, useAction } from "./hooks";

/**
 * Make an account the one copycat trades. The api refuses (409) while the
 * current account still has engine copies open: switching would leave them
 * on Hyperliquid with nobody managing them. We explain that and offer
 * Close all first (Portfolio) or Switch anyway (?force=true).
 */
export function ActivateButton({
  account, onActivated, label = "Activate", size = "sm",
}: {
  account: TradingAccount;
  onActivated?: () => void;
  label?: string;
  size?: ButtonProps["size"];
}) {
  const { demo, source } = useAccountMode();
  const act = useAction();
  const conflict = isOpenCopiesConflict(act.error) ? (act.error as Error).message : null;
  const copies = conflict?.match(/(\d+) copies/)?.[1] ?? null;

  async function activate(force: boolean) {
    const ok = await act.run(async () => {
      await source.activate(account.id, force);
      return true;
    });
    if (ok) onActivated?.();
  }

  return (
    <>
      <Button size={size} variant="primary" disabled={act.pending} onClick={() => activate(false)}>
        <Zap size={12} aria-hidden="true" /> {act.pending ? "Switching…" : label}
      </Button>
      <ErrorLine>{conflict ? null : accountErrorText(act.error, "activate")}</ErrorLine>
      <Dialog
        open={conflict !== null}
        onClose={act.clearError}
        title="Your current account still has copies open"
        description={
          <>
            <p>{copies ? `${copies} copies are open. ` : ""}If you switch to {account.label}, copycat stops managing them. They stay open on Hyperliquid with no exits, resizes or stops from copycat.</p>
            <p className="mt-2">Safer: close them first with Close all in Portfolio, then switch.</p>
          </>
        }
        footer={
          <>
            <Link
              href={`/portfolio${demo ? "?demo=1" : ""}`}
              onClick={() => {
                act.clearError();
                closeWalletManager();
              }}
              className="inline-flex items-center rounded-lg border border-border bg-surface-2 px-3.5 py-2 text-sm font-medium hover:bg-border"
            >
              Go to Close all
            </Link>
            <Button variant="danger" disabled={act.pending} onClick={() => activate(true)}>
              {act.pending ? "Switching…" : "Switch anyway"}
            </Button>
          </>
        }
      />
    </>
  );
}
