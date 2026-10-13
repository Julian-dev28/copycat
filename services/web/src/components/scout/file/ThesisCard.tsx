"use client";

import { useState } from "react";
import { Check, Copy, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Panel } from "@/components/ui/Panel";
import { buildToc, THESIS_SOURCE, thesisCommand, TOC_MIN_HEADINGS } from "@/lib/scout/file/strategy";
import type { Thesis } from "@/lib/scout/types";
import { SafeMarkdown } from "./SafeMarkdown";

function fmtDate(ms: number): string {
  return new Date(ms).toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
}

export function ThesisCard({ thesis, stale = false }: { thesis: Thesis; stale?: boolean }) {
  const src = THESIS_SOURCE[thesis.source];
  const toc = buildToc(thesis.markdown);
  return (
    <Panel className="flex flex-col gap-1 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={src.tone}>{src.label}</Badge>
        <span className="text-xs text-muted">{fmtDate(thesis.created_ms)}</span>
        {thesis.author ? <span className="text-xs text-muted">· {thesis.author}</span> : null}
        {stale ? (
          <Badge tone="warn" title="A newer fingerprint exists than the one this thesis cites; some numbers above may have moved on.">
            Stale
          </Badge>
        ) : null}
      </div>
      <h3 className="mt-1 text-[15px] font-semibold">{thesis.title}</h3>
      {thesis.source === "claude_code" ? (
        <p className="text-xs text-muted">Written by Claude Code from copycat data. Not financial advice.</p>
      ) : null}
      {toc.length >= TOC_MIN_HEADINGS ? (
        <nav aria-label={`${thesis.title} sections`} className="mt-1 flex flex-wrap gap-x-3 gap-y-1 border-b border-border pb-2 text-xs">
          {toc.map((t) => (
            <a key={t.id} href={`#${t.id}`} className={t.level === 3 ? "pl-2 text-muted underline underline-offset-2" : "text-accent underline underline-offset-2"}>
              {t.text}
            </a>
          ))}
        </nav>
      ) : null}
      <SafeMarkdown markdown={thesis.markdown} />
    </Panel>
  );
}

export function ThesisHint({ address }: { address: string }) {
  const [copied, setCopied] = useState(false);
  const cmd = thesisCommand(address);
  async function copy() {
    try {
      await navigator.clipboard.writeText(cmd);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }
  return (
    <Panel className="flex flex-col gap-2 border-dashed p-4">
      <div className="flex items-center gap-2 text-sm font-semibold">
        <Sparkles size={15} className="text-accent" aria-hidden="true" />
        Have Claude Code write a deeper thesis
      </div>
      <p className="text-sm text-muted">
        Run this in Claude Code. It reads this file through the copycat MCP server and saves its thesis here.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <code className="min-w-0 flex-1 break-all rounded-md bg-surface-2 px-2 py-1.5 font-num text-xs">{cmd}</code>
        <Button size="sm" onClick={copy} aria-label="Copy command">
          {copied ? <Check size={13} className="text-success" aria-hidden="true" /> : <Copy size={13} aria-hidden="true" />}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <p className="text-xs text-muted">
        First time: run <code className="font-num">make mcp-install</code> in the copycat repo.
      </p>
    </Panel>
  );
}
