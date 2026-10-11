"use client";

import { useEffect, useRef, useState } from "react";
import { Copy, Download } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import type { CurvePoint } from "@/lib/scout/types";
import { shareCardData, shareFileName, type ShareCardData } from "@/lib/trade/shareCard";
import type { WalletPosition } from "@/lib/trade/types";

const CW = 1200;
const CH = 630;
// The CatLogo geometry (components/CatLogo.tsx, 32x32 viewBox).
const CAT_HEAD = "M5 27V11.5L7.5 3.5L13 9h6l5.5-5.5L27 11.5V27a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2Z";
const ORANGE = "#ff7a1a";
const GREEN = "#3dd68c";
const RED = "#ff5c5c";

function drawCat(ctx: CanvasRenderingContext2D, x: number, y: number, size: number) {
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(size / 32, size / 32);
  ctx.fillStyle = ORANGE;
  ctx.fill(new Path2D(CAT_HEAD));
  ctx.fillStyle = "#0b0b0c";
  for (const [ex, op] of [[9.6, 0.45], [8.6, 1], [19.6, 0.45], [18.6, 1]] as const) {
    ctx.globalAlpha = op;
    const dy = op < 1 ? 13.6 : 14.6;
    ctx.fill(roundRect(ex, dy, 4.4, 4.4, 0.9));
  }
  ctx.globalAlpha = 1;
  ctx.fill(new Path2D("M15 21.2h2l-1 1.3z"));
  ctx.restore();
}

function roundRect(x: number, y: number, w: number, h: number, r: number): Path2D {
  const p = new Path2D();
  p.roundRect(x, y, w, h, r);
  return p;
}

/** The whole card, drawn from ShareCardData only (so nothing else can leak onto it). */
export function drawShareCard(ctx: CanvasRenderingContext2D, d: ShareCardData) {
  const g = ctx.createLinearGradient(0, 0, CW, CH);
  g.addColorStop(0, "#151411");
  g.addColorStop(1, "#0b0b0a");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, CW, CH);
  ctx.strokeStyle = "#2c2924";
  ctx.lineWidth = 2;
  ctx.strokeRect(1, 1, CW - 2, CH - 2);

  drawCat(ctx, 64, 52, 64);
  ctx.fillStyle = "#f3efe8";
  ctx.font = "700 40px ui-sans-serif, system-ui, sans-serif";
  ctx.textBaseline = "middle";
  ctx.fillText("copycat", 144, 86);

  // direction pill
  const pill = d.directionLabel.toUpperCase();
  ctx.font = "700 24px ui-sans-serif, system-ui, sans-serif";
  const pw = ctx.measureText(pill).width + 40;
  ctx.fillStyle = d.direction === "counter" ? "rgba(255,92,92,0.15)" : "rgba(255,122,26,0.15)";
  ctx.fill(roundRect(CW - 64 - pw, 62, pw, 48, 24));
  ctx.fillStyle = d.direction === "counter" ? RED : ORANGE;
  ctx.fillText(pill, CW - 64 - pw + 20, 87);

  ctx.fillStyle = "#f3efe8";
  ctx.font = "600 36px ui-sans-serif, system-ui, sans-serif";
  ctx.fillText(d.title, 64, 182);
  ctx.fillStyle = "#9b9488";
  ctx.font = "400 26px ui-monospace, SFMono-Regular, monospace";
  ctx.fillText(d.title === d.shortAddress ? d.period : `${d.shortAddress} · ${d.period}`, 64, 226);

  const tone = d.up ? GREEN : RED;
  ctx.fillStyle = tone;
  ctx.font = "800 104px ui-monospace, SFMono-Regular, monospace";
  ctx.fillText(d.pnlText, 64, 330);

  const stats: [string, string][] = [["PnL % of exposure", d.pnlPctText], ["ROE", d.roeText]];
  stats.forEach(([label, value], i) => {
    const x = 64 + i * 300;
    ctx.fillStyle = "#9b9488";
    ctx.font = "500 22px ui-sans-serif, system-ui, sans-serif";
    ctx.fillText(label, x, 420);
    ctx.fillStyle = "#f3efe8";
    ctx.font = "700 44px ui-monospace, SFMono-Regular, monospace";
    ctx.fillText(value, x, 466);
  });

  // sparkline, right half
  if (d.spark.length >= 2) {
    const bx = 680;
    const by = 300;
    const bw = 456;
    const bh = 200;
    ctx.beginPath();
    d.spark.forEach((p, i) => {
      const px = bx + p.x * bw;
      const py = by + (1 - p.y) * bh;
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
    ctx.strokeStyle = tone;
    ctx.lineWidth = 4;
    ctx.lineJoin = "round";
    ctx.stroke();
  }

  ctx.fillStyle = "#6b6558";
  ctx.font = "400 20px ui-sans-serif, system-ui, sans-serif";
  ctx.fillText("Past results don't predict future ones. Not financial advice.", 64, CH - 48);
}

function toBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("could not render the image"))), "image/png"));
}

/** Share PnL: a branded PNG of one wallet row. Download, or copy the image to the clipboard. */
export function ShareCardDialog({
  open,
  onClose,
  wallet,
  name,
  nowMs,
  index,
}: {
  open: boolean;
  onClose: () => void;
  wallet: WalletPosition;
  name: string | null;
  nowMs: number;
  index?: CurvePoint[];
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [note, setNote] = useState<string | null>(null);
  const data = shareCardData(wallet, { name, nowMs, index });
  const dataKey = JSON.stringify(data);

  useEffect(() => {
    const ctx = ref.current?.getContext("2d");
    if (ctx) drawShareCard(ctx, JSON.parse(dataKey) as ShareCardData);
  }, [dataKey]);

  async function download() {
    if (!ref.current) return;
    const url = URL.createObjectURL(await toBlob(ref.current));
    const a = document.createElement("a");
    a.href = url;
    a.download = shareFileName(data);
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1_000);
    setNote("Saved.");
  }

  async function copy() {
    if (!ref.current) return;
    try {
      if (typeof ClipboardItem === "undefined" || !navigator.clipboard?.write) throw new Error("no image clipboard");
      await navigator.clipboard.write([new ClipboardItem({ "image/png": toBlob(ref.current) })]);
      setNote("Image copied.");
    } catch {
      setNote("This browser can't copy images: use Download.");
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Share your PnL"
      description="Only what's on your screen: the short address, direction, PnL, ROE and period. No allocation, balances or your own address."
      footer={
        <>
          {note ? <span role="status" className="mr-auto self-center text-xs text-muted">{note}</span> : null}
          <Button variant="ghost" onClick={onClose}>Close</Button>
          <Button variant="secondary" onClick={copy}><Copy size={13} aria-hidden="true" /> Copy image</Button>
          <Button variant="primary" onClick={download}><Download size={13} aria-hidden="true" /> Download</Button>
        </>
      }
    >
      <canvas ref={ref} width={CW} height={CH} className="w-full rounded-lg border border-border" aria-label={`PnL card: ${data.title}, ${data.directionLabel}, ${data.pnlText}, ROE ${data.roeText}, ${data.period}`} />
    </Dialog>
  );
}
