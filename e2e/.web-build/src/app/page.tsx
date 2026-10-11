import { Suspense } from "react";
import { PageSkeleton } from "@/components/PageStates";
import { TradePage } from "@/components/trade/TradePage";

/** Home: Trade. Every copyable wallet as a market; invest $X with your leverage. */
export default function HomePage() {
  return (
    <Suspense fallback={<PageSkeleton label="Loading Trade" />}>
      <TradePage />
    </Suspense>
  );
}
