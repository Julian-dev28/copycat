"use client";

import { Suspense } from "react";
import { AccountPage } from "@/components/account/AccountPage";
import { PageSkeleton } from "@/components/PageStates";
import { RequireToken } from "@/components/RequireToken";
import { useScoutMode } from "@/hooks/useScout";

export default function Page() {
  return (
    <Suspense fallback={<PageSkeleton label="Loading account" />}>
      <Gate />
    </Suspense>
  );
}

function Gate() {
  const { demo } = useScoutMode();
  return demo ? <AccountPage /> : (
    <RequireToken>
      <AccountPage />
    </RequireToken>
  );
}
