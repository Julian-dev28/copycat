import type { ReactNode } from "react";
import Markdown, { defaultUrlTransform, type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { slugify } from "@/lib/scout/file/strategy";

/**
 * Thesis markdown, rendered safely. Theses can come from an MCP client
 * (Claude Code), so treat them as untrusted:
 *   - no rehype-raw: raw HTML in the source is dropped (skipHtml), never parsed
 *   - images are not rendered (no tracking pixels), links open in a new tab
 *     with noopener and only http(s)/mailto survive the url transform
 */
const ALLOWED_PROTOCOL = /^(https?:|mailto:)/i;

export function safeUrl(url: string): string {
  const cleaned = defaultUrlTransform(url);
  if (!cleaned) return "";
  if (cleaned.startsWith("#") || cleaned.startsWith("/")) return cleaned;
  return ALLOWED_PROTOCOL.test(cleaned) ? cleaned : "";
}

/** Plain text of a heading's children, for the same slugify() the TOC uses
 * (lib/scout/file/strategy.ts: buildToc parses the same markdown source),
 * so a TOC link always lands on the heading it names. */
function textOf(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (typeof node === "object" && "props" in node) return textOf((node as { props: { children?: ReactNode } }).props.children);
  return "";
}

/** Per-render de-dupe so two identically-worded headings in one thesis get
 * distinct ids (first "risks", second "risks-2"), matching buildToc(). */
function headingId(seen: Map<string, number>, children: ReactNode): string {
  const base = slugify(textOf(children)) || "section";
  const n = seen.get(base) ?? 0;
  seen.set(base, n + 1);
  return n === 0 ? base : `${base}-${n + 1}`;
}

export function SafeMarkdown({ markdown }: { markdown: string }) {
  const seen = new Map<string, number>();
  const components: Components = {
    a: ({ href, children }) =>
      href ? (
        <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-accent underline underline-offset-2">
          {children}
        </a>
      ) : (
        <span>{children}</span>
      ),
    h1: ({ children }) => (
      <h3 id={headingId(seen, children)} className="mt-3 scroll-mt-20 text-sm font-semibold">
        {children}
      </h3>
    ),
    h2: ({ children }) => (
      <h3 id={headingId(seen, children)} className="mt-3 scroll-mt-20 text-sm font-semibold">
        {children}
      </h3>
    ),
    h3: ({ children }) => (
      <h4 id={headingId(seen, children)} className="mt-3 scroll-mt-20 text-[13px] font-semibold">
        {children}
      </h4>
    ),
    p: ({ children }) => <p className="mt-2 leading-relaxed">{children}</p>,
    ul: ({ children }) => <ul className="mt-2 list-disc space-y-1 pl-5">{children}</ul>,
    ol: ({ children }) => <ol className="mt-2 list-decimal space-y-1 pl-5">{children}</ol>,
    blockquote: ({ children }) => <blockquote className="mt-2 border-l-2 border-accent/50 pl-3 text-muted">{children}</blockquote>,
    code: ({ children }) => <code className="rounded bg-surface-2 px-1 py-0.5 font-num text-[12px]">{children}</code>,
    pre: ({ children }) => <pre className="mt-2 overflow-x-auto rounded-lg bg-surface-2 p-3 text-[12px]">{children}</pre>,
    table: ({ children }) => (
      <div className="mt-2 overflow-x-auto">
        <table className="w-full border-collapse text-xs">{children}</table>
      </div>
    ),
    th: ({ children }) => <th className="border-b border-border px-2 py-1 text-left font-medium text-muted">{children}</th>,
    td: ({ children }) => <td className="border-b border-border/60 px-2 py-1">{children}</td>,
    img: ({ alt }) => <span className="text-muted">[image: {alt || "not shown"}]</span>,
  };
  return (
    <div className="text-sm text-foreground">
      <Markdown remarkPlugins={[remarkGfm]} skipHtml urlTransform={safeUrl} components={components}>
        {markdown}
      </Markdown>
    </div>
  );
}
