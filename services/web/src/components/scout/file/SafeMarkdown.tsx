import Markdown, { defaultUrlTransform, type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

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

const components: Components = {
  a: ({ href, children }) =>
    href ? (
      <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-accent underline underline-offset-2">
        {children}
      </a>
    ) : (
      <span>{children}</span>
    ),
  h1: ({ children }) => <h3 className="mt-3 text-sm font-semibold">{children}</h3>,
  h2: ({ children }) => <h3 className="mt-3 text-sm font-semibold">{children}</h3>,
  h3: ({ children }) => <h4 className="mt-3 text-[13px] font-semibold">{children}</h4>,
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

export function SafeMarkdown({ markdown }: { markdown: string }) {
  return (
    <div className="text-sm text-foreground">
      <Markdown remarkPlugins={[remarkGfm]} skipHtml urlTransform={safeUrl} components={components}>
        {markdown}
      </Markdown>
    </div>
  );
}
