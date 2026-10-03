"use client";

import { RequireToken } from "@/components/RequireToken";
import { useSettings, usePatchSettings } from "@/hooks/useSettings";
import { useEngineStatus } from "@/hooks/useEngineStatus";
import { EngineControlsPanel } from "@/components/copy/EngineControlsPanel";
import { CopyBehaviorPanel } from "@/components/copy/CopyBehaviorPanel";
import { LeadersPanel } from "@/components/copy/LeadersPanel";
import { SaveStatusBadge } from "@/components/copy/SaveStatusBadge";
import type { SettingsPatch } from "@/lib/api/types";

export default function CopyPage() {
  return (
    <RequireToken>
      <CopyPageContent />
    </RequireToken>
  );
}

function CopyPageContent() {
  const { data: settings, isLoading, isError, error } = useSettings();
  const { data: status } = useEngineStatus();
  const patchSettings = usePatchSettings();

  function onPatch(patch: SettingsPatch) {
    patchSettings.mutate(patch);
  }

  if (isLoading) {
    return <p className="py-12 text-center text-sm text-muted">Loading settings…</p>;
  }

  if (isError || !settings) {
    return (
      <p className="py-12 text-center text-sm text-danger">
        Couldn&apos;t load settings{error instanceof Error ? `: ${error.message}` : ""}.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Copy settings</h1>
          <p className="text-sm text-muted">Configure how copycat mirrors your leaders.</p>
        </div>
        <SaveStatusBadge
          state={patchSettings.isPending ? "saving" : patchSettings.isError ? "error" : patchSettings.isSuccess ? "saved" : "idle"}
          errorMessage={patchSettings.error?.message}
        />
      </div>

      <CopyBehaviorPanel settings={settings} onPatch={onPatch} />
      <EngineControlsPanel settings={settings} onPatch={onPatch} />
      <LeadersPanel settings={settings} status={status} />
    </div>
  );
}
