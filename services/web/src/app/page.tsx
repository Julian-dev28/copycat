import { redirect } from "next/navigation";

/** /copy is home; this route exists only to send "/" there. */
export default function RootPage() {
  redirect("/copy");
}
