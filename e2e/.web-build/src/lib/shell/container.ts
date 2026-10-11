/**
 * One container system for the whole app (DESIGN.md 3.6, UX audit "global
 * shell"): the header, the demo strip and <main> all use the same width for
 * the current route, so the logo lines up with the page edge.
 *
 * - wide (85rem / 1360px): Trade, three columns.
 * - read (72rem): every other page.
 */

export type ContainerKind = "wide" | "read";

export const CONTAINER_CLASS: Record<ContainerKind, string> = {
  wide: "mx-auto w-full max-w-[85rem] px-4 sm:px-6",
  read: "mx-auto w-full max-w-6xl px-4 sm:px-6",
};

const WIDE = new Set(["/", "/trade"]);

export function containerFor(pathname: string | null): ContainerKind {
  return pathname && WIDE.has(pathname) ? "wide" : "read";
}

export function containerClass(pathname: string | null): string {
  return CONTAINER_CLASS[containerFor(pathname)];
}
