"use client";

import { useEffect, useRef } from "react";
import { scrollProgressPct } from "@/lib/shell/scrollProgress";

/**
 * The 1px accent line along the bottom edge of the header that grows with
 * the page scroll (reference pattern). Writes the width straight to the
 * element on a passive scroll listener: no React state, nothing re-renders.
 */
export function ScrollProgress() {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let raf = 0;
    const paint = () => {
      raf = 0;
      const d = document.documentElement;
      el.style.width = `${scrollProgressPct(window.scrollY, d.scrollHeight, window.innerHeight)}%`;
    };
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(paint);
    };
    paint();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);
  return <div ref={ref} aria-hidden="true" className="absolute bottom-0 left-0 h-px w-0 bg-accent transition-[width] duration-[var(--dur-fast)] ease-out" />;
}
