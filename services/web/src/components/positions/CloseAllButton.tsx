"use client";

import { useState } from "react";
import { XCircle } from "lucide-react";
import { isNotSupported } from "@/lib/api/client";
import { CLOSE_ALL_PHRASE, closeAllConfirmed } from "@/lib/confirm";
import { useCloseAllCopies } from "@/hooks/useEngineStatus";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";

export function CloseAllButton({ openCopies }: { openCopies: number }) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const closeAll = useCloseAllCopies();

  function openDialog() {
    setTyped("");
    closeAll.reset();
    setOpen(true);
  }

  function submit() {
    if (!closeAllConfirmed(typed) || closeAll.isPending) return;
    closeAll.mutate(undefined, { onSuccess: () => setOpen(false) });
  }

  const errorText = closeAll.isError
    ? isNotSupported(closeAll.error)
      ? "Not supported by this api version. Update the api to get POST /api/engine/close-all."
      : closeAll.error.message
    : null;

  return (
    <>
      <button
        type="button"
        onClick={openDialog}
        className="flex items-center gap-2 rounded-xl border border-danger/50 px-4 py-3 text-sm font-semibold text-danger transition-colors hover:bg-danger/10"
      >
        <XCircle size={18} aria-hidden="true" />
        Close all copies
      </button>
      {closeAll.isSuccess && !open ? (
        <p role="status" className="text-xs text-success">
          Close orders sent. Positions update on the next cycle.
        </p>
      ) : null}
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="Close every copy position?"
        description={
          <>
            {openCopies === 0
              ? "copycat doesn't see any open copies right now, so this should be a no-op. It still asks the engine to market-close anything it opened."
              : `Market-closes ${openCopies === 1 ? "the 1 open copy" : `all ${openCopies} open copies`} on Hyperliquid right now.`} Your leaders&apos; own positions are untouched, and the engine will open new copies again if trading is
            still on. Type <span className="font-num font-semibold text-foreground">{CLOSE_ALL_PHRASE}</span> to confirm.
          </>
        }
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={submit} disabled={!closeAllConfirmed(typed) || closeAll.isPending}>
              {closeAll.isPending ? "Closing…" : "Close all copies"}
            </Button>
          </>
        }
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <Input
            autoFocus
            autoComplete="off"
            spellCheck={false}
            aria-label={`Type ${CLOSE_ALL_PHRASE} to confirm`}
            placeholder={CLOSE_ALL_PHRASE}
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            className="font-num"
          />
          {errorText ? (
            <p role="alert" className="mt-2 text-sm text-danger">
              {errorText}
            </p>
          ) : null}
        </form>
      </Dialog>
    </>
  );
}
