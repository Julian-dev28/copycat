import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { safeUrl, SafeMarkdown } from "@/components/scout/file/SafeMarkdown";

const html = (markdown: string) => renderToStaticMarkup(createElement(SafeMarkdown, { markdown }));

describe("thesis markdown safety", () => {
  it("drops a <script> block and inline HTML", () => {
    const out = html('Hello\n\n<script>alert("x")</script>\n\n<img src=x onerror="alert(1)"> and <b>bold</b>');
    expect(out).not.toContain("<script");
    expect(out).not.toContain("onerror");
    expect(out).not.toContain("<b>");
    expect(out).toContain("Hello");
  });

  it("neutralises javascript: and data: links", () => {
    const out = html("[a](javascript:alert(1)) [b](data:text/html,hi) [c](https://example.com)");
    expect(out).not.toContain("javascript:");
    expect(out).not.toContain("data:text");
    expect(out).toContain('href="https://example.com"');
    expect(out).toContain('rel="noopener noreferrer nofollow"');
    expect(safeUrl("vbscript:x")).toBe("");
  });

  it("never renders images (no tracking pixels)", () => {
    const out = html("![pixel](https://evil.example/p.gif)");
    expect(out).not.toContain("<img");
    expect(out).toContain("[image: pixel]");
  });

  it("still renders GFM tables, lists and emphasis", () => {
    const out = html("**bold**\n\n- one\n\n| a | b |\n|---|---|\n| 1 | 2 |");
    expect(out).toContain("<strong>bold</strong>");
    expect(out).toContain("<li>");
    expect(out).toContain("<table");
  });
});
