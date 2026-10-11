"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/context/AuthContext";
import { Drawer } from "@/components/ui/Drawer";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { getApiBase } from "@/lib/api/client";
import { useSyncedState } from "@/hooks/useSyncedState";
import { TokenWhereToFind } from "@/components/RequireToken";

export function SettingsDrawer() {
  const { drawerOpen, closeDrawer, token, setToken, clearToken, unauthorized, hasToken } = useAuth();
  // Follows the stored token: it's undefined during hydration, so a plain
  // useState initializer would leave the field empty with a token stored.
  const [draft, setDraft] = useSyncedState(token ?? "");
  const qc = useQueryClient();

  function handleSave() {
    const trimmed = draft.trim();
    if (!trimmed) return;
    setToken(trimmed);
    qc.invalidateQueries();
    closeDrawer();
  }

  function handleClear() {
    clearToken();
    setDraft("");
    qc.clear();
  }

  return (
    <Drawer open={drawerOpen} onClose={closeDrawer} title="API token" closeLabel="Close API token">
      <div className="flex flex-col gap-5">
        <div>
          <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">API connection</h3>
          <p className="mt-1 text-xs text-muted">
            Talking to <span className="font-num text-foreground">{getApiBase()}</span>. Override with{" "}
            <span className="font-num">NEXT_PUBLIC_COPYCAT_API</span> at build/run time.
          </p>
        </div>

        {unauthorized ? (
          <div className="rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            The api rejected the last request (401). The token may have been regenerated: paste the current one below.
          </div>
        ) : null}

        <div className="flex flex-col gap-2">
          <label htmlFor="api-token" className="text-sm font-medium text-foreground">
            Bearer token
          </label>
          <Input
            id="api-token"
            type="password"
            autoComplete="off"
            placeholder="COPYCAT_API_TOKEN"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSave();
            }}
          />
          <TokenWhereToFind className="" />
          <p className="text-xs text-muted">Stored only in this browser&apos;s localStorage.</p>
        </div>

        <div className="flex gap-2">
          <Button variant="primary" onClick={handleSave} disabled={!draft.trim()}>
            Save token
          </Button>
          {hasToken ? (
            <Button variant="ghost" onClick={handleClear}>
              Clear
            </Button>
          ) : null}
        </div>
      </div>
    </Drawer>
  );
}
