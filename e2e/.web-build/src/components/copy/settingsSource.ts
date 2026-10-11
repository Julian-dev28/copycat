/**
 * Where /settings reads and writes. Live: the api. Demo (`?demo=1`): the Trade
 * page's in-memory book (lib/trade/source.ts demoTrade), so Settings and Trade
 * agree on one demo account and nothing reaches the api (UX audit #1).
 */
import { api } from "@/lib/api/client";
import type { EngineStatus, Settings, SettingsPatch } from "@/lib/api/types";
import { applySettingsPatch } from "@/lib/settings";
import type { TradeSource } from "@/lib/trade/source";
import type { TradeSettings } from "@/lib/trade/types";

export interface SettingsSource {
  readonly demo: boolean;
  settings(): Promise<Settings>;
  status(): Promise<EngineStatus>;
  patch(patch: SettingsPatch): Promise<Settings>;
  addLeader(address: string): Promise<Settings>;
  removeLeader(address: string): Promise<Settings>;
}

export const liveSettingsSource: SettingsSource = {
  demo: false,
  settings: () => api.getSettings(),
  status: () => api.getStatus(),
  patch: (p) => api.patchSettings(p),
  addLeader: (a) => api.addLeader(a),
  removeLeader: (a) => api.removeLeader(a),
};

const asSettings = (s: TradeSettings) => s as unknown as Settings;

/**
 * Settings over a demo TradeSource. Its `patch` is a shallow merge, so every
 * write sends whole fields computed with the api's own PATCH semantics
 * (applySettingsPatch: leader_overrides merge per leader, null clears one).
 */
export function demoSettingsSource(trade: TradeSource): SettingsSource {
  const write = async (f: (s: Settings) => Settings) => {
    const next = f(asSettings(await trade.settings()));
    return asSettings(await trade.patch(next as unknown as Partial<TradeSettings>));
  };
  return {
    demo: true,
    settings: async () => asSettings(await trade.settings()),
    status: async () => (await trade.status()) as unknown as EngineStatus,
    patch: (p) => write((s) => applySettingsPatch(s, p)),
    addLeader: (address) =>
      write((s) => (s.leaders.includes(address) ? s : { ...s, leaders: [...s.leaders, address] })),
    removeLeader: (address) =>
      write((s) => {
        const { [address]: _gone, ...rest } = s.leader_overrides;
        return { ...s, leaders: s.leaders.filter((a) => a !== address), leader_overrides: rest };
      }),
  };
}
