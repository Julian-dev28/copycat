import type { CSSProperties } from "react";
import { CatLogo } from "@/components/CatLogo";

/** Stable hue per address (FNV-1a), so a wallet keeps its color everywhere. */
export function addressHue(address: string): number {
  let h = 2166136261;
  for (let i = 0; i < address.length; i++) h = Math.imul(h ^ address.charCodeAt(i), 16777619);
  return (h >>> 0) % 360;
}

/** The ticker icon of a wallet: our cat mark on a tile tinted by the address. */
export function CatAvatar({ address, size = 28 }: { address: string; size?: number }) {
  const hue = addressHue(address.toLowerCase());
  const style = {
    width: size,
    height: size,
    background: `hsl(${hue} 70% 50% / 0.16)`,
    color: `hsl(${hue} 75% 58%)`,
    "--cat-eye": "var(--surface)",
  } as CSSProperties;
  return (
    <span aria-hidden="true" className="inline-flex flex-shrink-0 items-center justify-center rounded-lg" style={style}>
      <CatLogo size={Math.round(size * 0.68)} title="" />
    </span>
  );
}
