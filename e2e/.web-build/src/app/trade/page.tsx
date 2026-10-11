import { redirect } from "next/navigation";
import { legacyRedirect } from "@/lib/trade/apiState";

/** /trade is the home page; keep the link working (and its ?w=, ?demo=). */
export default async function TradeRedirect({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  redirect(legacyRedirect("/trade", await searchParams));
}
