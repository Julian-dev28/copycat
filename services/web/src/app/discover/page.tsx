import { redirect } from "next/navigation";
import { legacyRedirect } from "@/lib/trade/apiState";

/** /discover retired (contract v16): the Scout board's own sim terms, changeable on the
 * fly in its toolbar, replace the separate custom-sim page and its -200 scores. */
export default async function DiscoverRedirect({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  redirect(legacyRedirect("/discover", await searchParams));
}
