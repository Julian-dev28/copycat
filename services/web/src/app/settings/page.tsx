"use client";

import { RequireToken } from "@/components/RequireToken";
import { useSettings, usePatchSettings } from "@/hooks/useSettings";
import { useEngineStatus } from "@/hooks/useEngineStatus";
import { EngineControlsPanel } from "@/components/copy/EngineControlsPanel";
import { CopyBehaviorPanel } from "@/components/copy/CopyBehaviorPanel";
import { LeadersPanel } from "@/components/copy/LeadersPanel";
import { SaveStatusBadge } from "@/components/copy/SaveStatusBadge";
import { CopyRecipeCard } from "@/components/copy/CopyRecipeCard";
import { EmptyAccountBanner } from "@/components/EmptyAccountBanner";
import { LoadError, PageSkeleton } from "@/components/PageStates";
import type { SettingsPatch } from "@/lib/api/types";
import { ApiTokenPanel, TradeDefaultsPanel } from "./TradeDefaultsPanel";

/** Global settings (was /copy): trading on/off, dry run, defaults, risk limits, the token. */
export default function SettingsPage() {
  return (
    <div className="flex flex-col gap-6">
      <RequireToken>
        <SettingsContent />
      </RequireToken>
    </div>
  );
}

function SettingsContent() {
  const { data: settings, isLoading, isError, error, refetch } = useSettings();
  const { data: status } = useEngineStatus();
  const patchSettings = usePatchSettings();
  const onPatch = (patch: SettingsPatch) => patchSettings.mutate(patch);

  if (isLoading) return <PageSkeleton label="Loading settings" />;
  if (isError || !settings) return <LoadError what="settings" error={error} onRetry={() => refetch()} />;

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Settings</h1>
          <p className="text-sm text-muted">Applies to every wallet you copy. Changes save as you go.</p>
        </div>
        <SaveStatusBadge
          state={patchSettings.isPending ? "saving" : patchSettings.isError ? "error" : patchSettings.isSuccess ? "saved" : "idle"}
          errorMessage={patchSettings.error?.message}
        />
      </div>
      <EmptyAccountBanner status={status} settings={settings} />
      <EngineControlsPanel settings={settings} onPatch={onPatch} />
      <TradeDefaultsPanel settings={settings} onPatch={onPatch} />
      <CopyBehaviorPanel settings={settings} onPatch={onPatch} />
      <CopyRecipeCard settings={settings} status={status} />
      <LeadersPanel settings={settings} status={status} />
      <ApiTokenPanel />
    </>
  );
}
