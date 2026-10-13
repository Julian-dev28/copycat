/** The same URL with demo mode (and its demo-only params) removed. */
export function exitDemoHref(pathname: string | null, search: string): string {
  const p = new URLSearchParams(search);
  p.delete("demo");
  p.delete("acct");
  const qs = p.toString();
  return `${pathname || "/"}${qs ? `?${qs}` : ""}`;
}
