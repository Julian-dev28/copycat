"use client";

import type { ReactNode } from "react";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/Button";
import { Panel } from "@/components/ui/Panel";

/** Where the token comes from. The api generates one into data/api_token when COPYCAT_API_TOKEN is unset. */
export function TokenWhereToFind({ className = "mt-3" }: { className?: string }) {
  return (
    <p className={`${className} text-xs text-muted`}>
      It&apos;s <span className="font-num text-foreground">COPYCAT_API_TOKEN</span> from your .env, or, if that&apos;s unset,
      the token the api generated on first start:{" "}
      <span className="font-num whitespace-nowrap text-foreground">cat data/api_token</span>
    </p>
  );
}

/** Gates a page behind "enter your token" when no bearer token is set (or the api 401'd). */
export function RequireToken({ children }: { children: ReactNode }) {
  const { hasToken, unauthorized, openDrawer } = useAuth();

  if (!hasToken || unauthorized) {
    return (
      <div className="mx-auto mt-16 max-w-md">
        <Panel className="p-6 text-center">
          <h2 className="text-base font-semibold">
            {unauthorized ? "Token rejected" : "Enter your API token"}
          </h2>
          <p className="mt-2 text-sm text-muted">
            {unauthorized
              ? "The api rejected the stored bearer token (401). It may have been regenerated. Paste the current one in settings."
              : "copycat needs the api's bearer token to read or change anything."}
          </p>
          <TokenWhereToFind />
          <Button variant="primary" className="mt-4" onClick={openDrawer}>
            Open settings
          </Button>
        </Panel>
      </div>
    );
  }

  return <>{children}</>;
}
