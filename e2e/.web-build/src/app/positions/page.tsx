import { redirect } from "next/navigation";
import { legacyRedirect } from "@/lib/trade/apiState";

/** /positions was folded into /portfolio. */
export default async function PositionsRedirect({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  redirect(legacyRedirect("/positions", await searchParams));
}
