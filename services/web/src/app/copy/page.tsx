import { redirect } from "next/navigation";
import { legacyRedirect } from "@/lib/trade/apiState";

/** /copy moved to /settings. */
export default async function CopyRedirect({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  redirect(legacyRedirect("/copy", await searchParams));
}
