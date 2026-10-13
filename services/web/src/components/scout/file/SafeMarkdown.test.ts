import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { safeUrl, SafeMarkdown } from "./SafeMarkdown";

/** Theses render third-party / MCP-written markdown (a trader's thesis can
 * be authored by any MCP client). These pin the safety properties the
 * component's own comment promises: no raw HTML, no images, only
 * http(s)/mailto links -- with a real render, not just the url filter, so
 * a future change to the `components` map that reintroduces raw HTML or
 * drops the img override fails here, not in production. (.ts + createElement,
 * not JSX, because vitest.config.mts only collects *.test.ts.) */

function render(markdown: string): string {
  return renderToStaticMarkup(createElement(SafeMarkdown, { markdown }));
}

describe("safeUrl", () => {
  it("allows http, https and mailto", () => {
    expect(safeUrl("https://app.hyperliquid.xyz")).toBe("https://app.hyperliquid.xyz");
    expect(safeUrl("http://example.com")).toBe("http://example.com");
    expect(safeUrl("mailto:a@b.com")).toBe("mailto:a@b.com");
  });

  it("allows in-page anchors and root-relative paths", () => {
    expect(safeUrl("#edge-in-one-sentence")).toBe("#edge-in-one-sentence");
    expect(safeUrl("/scout/0xabc")).toBe("/scout/0xabc");
  });

  it("blocks script-executing and data schemes", () => {
    for (const url of [
      "javascript:alert(1)",
      "JAVASCRIPT:alert(1)",
      "data:text/html,<script>alert(1)</script>",
      "vbscript:msgbox(1)",
      "file:///etc/passwd",
    ]) {
      expect(safeUrl(url)).toBe("");
    }
  });
});

describe("SafeMarkdown render", () => {
  it("drops raw HTML instead of parsing it", () => {
    const html = render('before <script>alert(1)</script> <img src=x onerror="alert(2)"> after');
    expect(html).not.toContain("<script");
    expect(html).not.toContain("onerror");
    expect(html).toContain("before");
    expect(html).toContain("after");
  });

  it("never renders an <img> tag, even for valid markdown image syntax", () => {
    const html = render("![a trade chart](https://evil.example/track.png)");
    expect(html).not.toContain("<img");
    expect(html).toContain("[image: a trade chart]");
    expect(render("![](https://evil.example/track.png)")).toContain("not shown");
  });

  it("strips a javascript: link href but keeps the link text", () => {
    const html = render("[click me](javascript:alert(document.cookie))");
    expect(html.toLowerCase()).not.toContain("javascript:");
    expect(html).not.toContain("<a ");
    expect(html).toContain("click me");
  });

  it("keeps a real https link, opened safely in a new tab", () => {
    const html = render("[docs](https://hyperliquid.gitbook.io)");
    expect(html).toContain('href="https://hyperliquid.gitbook.io"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain("noopener");
  });

  it("gives every rendered heading an id, de-duped when headings repeat", () => {
    const html = render(["## Risks", "body", "## Risks"].join("\n"));
    expect(html).toContain('id="risks"');
    expect(html).toContain('id="risks-2"');
  });
});
