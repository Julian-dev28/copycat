"use client";

import { useState } from "react";
import { apiProblem } from "@/lib/trade/apiState";
import { mergePreview } from "@/lib/trade/apiPreview";
import { apiCaps, buildCopyRequest, effective, initialDraft, inherit, switchesSource, ticketAction, type InheritableField, type TicketDraft } from "@/lib/trade/draft";
import { checkAmount, maxInvest, parseInvest } from "@/lib/trade/form";
import { localPreview } from "@/lib/trade/preview";
import type { TicketPreview } from "@/lib/trade/ticket";
import type { TradeSettings, TradeStatus, WalletPosition } from "@/lib/trade/types";
import type { TraderProfile } from "@/lib/scout/types";
import { useWalletPreview } from "./hooks";

/**
 * Ticket state for one wallet. The draft resets to the saved terms only when
 * those terms change (a save landed, another wallet was picked), never on the
 * 4s status poll, so typing is never clobbered. Adjusted during render, not in
 * an effect (see hooks/useSyncedState.ts).
 */
export function useTicket(address: string | null, profile: TraderProfile | undefined, settings: TradeSettings | undefined, status: TradeStatus | undefined, wallet: WalletPosition | null) {
  const saved = initialDraft(settings, address, wallet);
  const invested = Boolean(wallet && wallet.in_book !== false);
  const savedKey = `${address}|${JSON.stringify(saved)}|${invested}`;
  const [state, setState] = useState({ key: savedKey, draft: saved });
  let draft = state.draft;
  if (state.key !== savedKey) {
    setState({ key: savedKey, draft: saved });
    draft = saved;
  }
  const setDraft = (patch: Partial<TicketDraft>) => setState((s) => ({ ...s, draft: { ...s.draft, ...patch } }));
  const resetField = (field: InheritableField) => setState((s) => ({ ...s, draft: inherit(s.draft, field) }));

  const caps = apiCaps(settings);
  const eff = effective(draft, settings);
  const custom = draft.source === "custom";
  const amount = custom ? parseInvest(draft.amountText) : null;
  const maxUsd = maxInvest(status?.available_margin_usd, wallet?.margin_used_usd ?? 0);
  const check = custom ? checkAmount(amount, maxUsd) : ({ ok: true, warn: null } as const);
  const body = address && check.ok ? buildCopyRequest(draft, caps) : null;
  const savedForCompare = invested ? saved : null;
  const action = ticketAction(draft, savedForCompare, invested);
  const switching = switchesSource(draft, savedForCompare, invested);

  const otherExposure = (status?.positions ?? []).filter((c) => c.leader !== address).reduce((a, c) => a + Math.abs(c.notional_usd), 0);
  // Local estimate only for custom terms; global sizing can be any mode, so it waits for the engine.
  const local: TicketPreview | null = profile && custom
    ? localPreview({
        allocationUsd: amount ?? 0,
        mode: draft.mode,
        targetLeverage: draft.leverage,
        marginMode: eff.marginMode,
        smallMode: caps.smallMode ? eff.smallMode : "skip",
        leaderEquityUsd: profile.row.account_value_usd,
        positions: profile.positions,
        maxPositionLeverage: settings?.max_position_leverage,
        ourEquityUsd: status?.equity_usd,
        otherExposureUsd: otherExposure,
      })
    : null;
  const api = useWalletPreview(address, body);
  const apiFailed = apiProblem(api.error);
  const fresh = api.settled && body && api.data && !api.isPlaceholderData ? api.data : null;
  const preview = local ? mergePreview(fresh, local) : fresh;
  const previewNote =
    apiFailed === "too_old" ? "Local estimate: your api has no preview route yet." : apiFailed ? "Local estimate: the engine preview failed." : null;

  return {
    draft, setDraft, resetField, amount, maxUsd, check, body, action, switching, invested, saved, caps, eff,
    preview, previewPending: Boolean(body) && (!api.settled || api.isFetching), previewNote, previewError: apiFailed,
  };
}
