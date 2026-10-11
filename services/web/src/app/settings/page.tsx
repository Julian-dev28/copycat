"use client";

import { Suspense } from "react";
import { RequireToken } from "@/components/RequireToken";
import { useModePatchSettings, useModeSettings, useModeStatus, useSettingsMode } from "@/components/copy/hooks";
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
      <Suspense fallback={<PageSkeleton label="Loading settings" />}>
        <SettingsGate />
      </Suspense>
    </div>
  );
}

/** Demo (`?demo=1`) runs on the Trade demo book with no token; live needs the api token. */
function SettingsGate() {
  const { demo } = useSettingsMode();
  if (demo) return <SettingsContent demo />;
  return (
    <RequireToken>
      <SettingsContent demo={false} />
    </RequireToken>
  );
}

function SettingsContent({ demo }: { demo: boolean }) {
  const { data: settings, isLoading, isError, error, refetch } = useModeSettings();
  const { data: status } = useModeStatus();
  const patchSettings = useModePatchSettings();
  const onPatch = (patch: SettingsPatch) => patchSettings.mutate(patch);

  if (isLoading) return <PageSkeleton label="Loading settings" />;
  if (isError || !settings) return <LoadError what="settings" error={error} onRetry={() => refetch()} />;

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Settings</h1>
          <p className="text-sm text-muted">
            {demo
              ? "Demo settings: they change the demo copies in this tab only, never your account."
              : "Applies to every wallet you copy. Changes save as you go."}
          </p>
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
      {demo ? null : <ApiTokenPanel />}
    </>
  );
}
