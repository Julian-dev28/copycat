"use client";

import type { ReactNode } from "react";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/Button";
import { Panel } from "@/components/ui/Panel";

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
              ? "The api rejected the stored bearer token (401). Open settings and enter a valid one."
              : "copycat needs the bearer token that matches COPYCAT_API_TOKEN on the api to read or change anything."}
          </p>
          <Button variant="primary" className="mt-4" onClick={openDrawer}>
            Open settings
          </Button>
        </Panel>
      </div>
    );
  }

  return <>{children}</>;
}
