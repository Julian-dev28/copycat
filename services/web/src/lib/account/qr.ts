/**
 * QR code for a deposit address, as one SVG path. Encoding is uqr (unjs,
 * zero deps, ~10 kB); this file only turns its boolean matrix into a path
 * so the component renders plain JSX (no innerHTML). Pure.
 */
import { encode } from "uqr";

export interface QrPath {
  /** Modules per side, quiet zone included. */
  size: number;
  /** "M x y h1 v1 h-1 z ..." for every dark module, in module units. */
  d: string;
}

/** 4 modules of quiet zone, as the QR spec asks for reliable scanning. */
export function qrPath(text: string, border = 4): QrPath {
  const { data, size } = encode(text, { ecc: "M", border });
  const parts: string[] = [];
  for (let y = 0; y < size; y++) {
    let x = 0;
    while (x < size) {
      if (!data[y][x]) {
        x++;
        continue;
      }
      // merge horizontal runs into one rect: fewer path commands, crisper rendering
      let run = 1;
      while (x + run < size && data[y][x + run]) run++;
      parts.push(`M${x} ${y}h${run}v1h-${run}z`);
      x += run;
    }
  }
  return { size, d: parts.join("") };
}

