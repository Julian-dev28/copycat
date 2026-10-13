"use client";

import { useEffect } from "react";
import { revealDelays } from "@/lib/shell/reveal";

/**
 * Scroll reveal (globals.css "Scroll reveal"): every [data-reveal] element
 * fades in and rises the first time it enters the viewport, cascading within
 * a batch. Mounted once in the root layout; watches for elements added later
 * (client navigation, lists that load). `html.reveal-ready` is set only here,
 * so without JS, or under reduced motion, nothing is ever hidden.
 */
export function RevealObserver() {
  useEffect(() => {
    const root = document.documentElement;
    if (typeof IntersectionObserver === "undefined" || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    root.classList.add("reveal-ready");
    const io = new IntersectionObserver(
      (entries) => {
        const shown = entries.filter((e) => e.isIntersecting).map((e) => e.target as HTMLElement);
        const delays = revealDelays(shown.length);
        shown.forEach((el, i) => {
          el.style.setProperty("--reveal-delay", `${delays[i]}ms`);
          el.classList.add("is-visible");
          io.unobserve(el);
        });
      },
      { rootMargin: "0px 0px -6% 0px", threshold: 0.05 },
    );
    const watch = (scope: ParentNode) =>
      scope.querySelectorAll<HTMLElement>("[data-reveal]:not(.is-visible)").forEach((el) => io.observe(el));
    watch(document);
    const mo = new MutationObserver((muts) => {
      for (const m of muts) m.addedNodes.forEach((n) => {
        if (!(n instanceof HTMLElement)) return;
        if (n.matches("[data-reveal]:not(.is-visible)")) io.observe(n);
        watch(n);
      });
    });
    mo.observe(document.body, { childList: true, subtree: true });
    return () => {
      io.disconnect();
      mo.disconnect();
      root.classList.remove("reveal-ready");
    };
  }, []);
  return null;
}
