"use client";

import { useState } from "react";
import type { EngineStatus, LeaderOverride, Settings } from "@/lib/api/types";
import { MAX_LEADERS } from "@/lib/api/types";
import { isValidAddress, normAddr } from "@/lib/address";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { LeaderRow } from "./LeaderRow";
import { useModeAddLeader, useModePatchSettings, useModeRemoveLeader, useSettingsMode } from "./hooks";

export function LeadersPanel({ settings, status }: { settings: Settings; status?: EngineStatus }) {
  const [addressDraft, setAddressDraft] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const addLeader = useModeAddLeader();
  const removeLeader = useModeRemoveLeader();
  const patchSettings = useModePatchSettings();
  const { demo } = useSettingsMode();

  const atCap = settings.leaders.length >= MAX_LEADERS;

  function handleAdd() {
    const address = normAddr(addressDraft);
    if (!isValidAddress(address)) {
      setFormError("not a valid 0x address");
      return;
    }
    if (settings.leaders.includes(address)) {
      setFormError("already copying this address");
      return;
    }
    setFormError(null);
    addLeader.mutate(address, {
      onSuccess: () => setAddressDraft(""),
      onError: (err) => setFormError(err.message),
    });
  }

  return (
    <Panel>
      <PanelHeader
        title={`Copies (${settings.leaders.length}/${MAX_LEADERS})`}
        description="Traders you copy. Expand a row to override any global setting for just that trader."
      />
      <div className="flex flex-col gap-2 border-t border-border px-4 py-3 sm:flex-row sm:items-start sm:px-5">
        <div className="flex-1">
          <Input
            placeholder="0x…"
            value={addressDraft}
            onChange={(e) => {
              setAddressDraft(e.target.value);
              setFormError(null);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleAdd();
            }}
            disabled={atCap}
            aria-label="Trader address"
            aria-invalid={Boolean(formError)}
            aria-describedby={formError ? "add-leader-error" : undefined}
          />
          {formError ? (
            <p id="add-leader-error" className="mt-1 text-xs text-danger">
              {formError}
            </p>
          ) : atCap ? (
            <p className="mt-1 text-xs text-muted">Max {MAX_LEADERS} copies. Remove one to add another.</p>
          ) : null}
        </div>
        <Button variant="primary" onClick={handleAdd} disabled={atCap || !addressDraft.trim() || addLeader.isPending}>
          Add
        </Button>
      </div>

      {settings.leaders.length === 0 ? (
        <p className="border-t border-border px-4 py-6 text-center text-sm text-muted sm:px-5">
          No copies yet. Add a trader&apos;s address above, or find one on{" "}
          <a href={demo ? "/scout?demo=1" : "/scout"} className="text-accent underline-offset-2 hover:underline">
            Scout
          </a>
          .
        </p>
      ) : (
        <div>
          {settings.leaders.map((address) => (
            <LeaderRow
              key={address}
              address={address}
              settings={settings}
              liveStatus={status?.leaders.find((l) => l.address === address)}
              removing={removeLeader.isPending && removeLeader.variables === address}
              onRemove={() => removeLeader.mutate(address)}
              onOverrideChange={(override: LeaderOverride | null) =>
                patchSettings.mutate({ leader_overrides: { [address]: override } })
              }
            />
          ))}
        </div>
      )}
    </Panel>
  );
}
