"use client";

import { CheckCircle2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { AddressChip } from "@/components/ui/AddressChip";
import type { TradingAccount } from "@/lib/account/types";
import { ApiKeyForm } from "./ApiKeyForm";
import { ActivateButton } from "./ActivateButton";
import { AgentBanner } from "./bits";
import { SignWithWallet } from "./SignWithWallet";

type Tab = "sign" | "key";

/** After any successful add: what was added, and one click to make it the account copycat trades. */
export function AddedPanel({ account, onClose }: { account: TradingAccount; onClose: () => void }) {
  const [activated, setActivated] = useState(account.active);
  return (
    <div className="flex flex-col items-center gap-3 py-2 text-center">
      <CheckCircle2 size={36} className="text-success" aria-hidden="true" />
      <div>
        <p className="text-base font-semibold">{account.label} is connected</p>
        <AddressChip address={account.address} className="mt-1" />
      </div>
      <p className="max-w-sm text-sm text-muted">
        {activated ? "copycat now trades this account." : "copycat keeps trading your current active account until you switch."}
      </p>
      <div className="flex flex-wrap justify-center gap-2">
        {activated ? null : <ActivateButton account={account} label="Make active" size="md" onActivated={() => setActivated(true)} />}
        <Button onClick={onClose}>Done</Button>
      </div>
    </div>
  );
}

export function ConnectWallet({
  initialTab = "sign", refresh, onClose,
}: {
  initialTab?: Tab;
  refresh?: { label: string; address: string };
  onClose: () => void;
}) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const [added, setAdded] = useState<TradingAccount | null>(null);

  if (added) return refresh ? <RefreshedPanel onClose={onClose} /> : <AddedPanel account={added} onClose={onClose} />;

  return (
    <div className="flex flex-col gap-4">
      <AgentBanner compact />
      <SegmentedControl
        aria-label="How to connect"
        options={[
          { value: "sign", label: "Sign with wallet" },
          { value: "key", label: "API key" },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === "sign" ? <SignWithWallet refresh={refresh} onDone={setAdded} /> : <ApiKeyForm refresh={refresh} onDone={setAdded} />}
    </div>
  );
}

function RefreshedPanel({ onClose }: { onClose: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 py-2 text-center">
      <CheckCircle2 size={36} className="text-success" aria-hidden="true" />
      <p className="text-base font-semibold">Trading agent renewed</p>
      <Button onClick={onClose}>Done</Button>
    </div>
  );
}
