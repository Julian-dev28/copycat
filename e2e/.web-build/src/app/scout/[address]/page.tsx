"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";
import { RequireToken } from "@/components/RequireToken";
import { PageSkeleton } from "@/components/PageStates";
import { TraderFile } from "@/components/scout/file/TraderFile";
import { useScoutMode } from "@/hooks/useScout";

export default function TraderFilePage() {
  return (
    <Suspense fallback={<PageSkeleton label="Loading trader file" rows={4} />}>
      <Gate />
    </Suspense>
  );
}

/** Demo mode (`?demo=1`) needs no token; live mode goes through the token gate. */
function Gate() {
  const params = useParams<{ address: string }>();
  const address = decodeURIComponent(params.address ?? "");
  const { demo } = useScoutMode();
  return demo ? (
    <TraderFile address={address} />
  ) : (
    <RequireToken>
      <TraderFile address={address} />
    </RequireToken>
  );
}
