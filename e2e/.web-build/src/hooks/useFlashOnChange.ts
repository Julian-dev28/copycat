"use client";

import { useEffect, useRef, useState } from "react";
import { DURATION, nextFlash, type FlashDirection } from "@/lib/display/motion";

/**
 * Flash a cell when its value changes (DESIGN 4.4): returns the class to put
 * on the cell for one --dur-flash, throttled to one flash per 2s. The number
 * itself renders immediately; the flash only decorates the arrival. Under
 * reduced motion globals.css swaps the fade for a static 2px left tint.
 */
export function useFlashOnChange(value: number | null | undefined): string {
  const prev = useRef(value);
  const lastAt = useRef<number | null>(null);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const [flash, setFlash] = useState<FlashDirection | null>(null);

  useEffect(() => {
    const now = Date.now();
    const dir = nextFlash(prev.current, value, lastAt.current, now);
    prev.current = value;
    if (!dir) return;
    lastAt.current = now;
    // Timers live in a ref: a later change inside the flash window must not
    // cancel the end timer (that would leave the cell tinted).
    timers.current.push(
      setTimeout(() => setFlash(dir), 0),
      setTimeout(() => setFlash(null), DURATION.flash),
    );
  }, [value]);

  useEffect(() => {
    const list = timers.current; // same array for the hook's life
    return () => list.forEach(clearTimeout);
  }, []);

  if (!flash) return "";
  return flash === "up" ? "animate-flash-up" : "animate-flash-down";
}
