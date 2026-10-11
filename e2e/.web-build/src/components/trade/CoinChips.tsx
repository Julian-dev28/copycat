"use client";

import { useId, useState, type KeyboardEvent } from "react";
import { clsx } from "clsx";
import { X } from "lucide-react";
import { addCoin, coinKey, parseCoins, suggestCoins } from "@/lib/trade/coinFilter";

/**
 * Chip input for a coin list with autocomplete: his coins first, then the
 * wider list. Enter, comma or Tab adds; Backspace on empty removes the last;
 * pasting "BTC, ETH SOL" adds all three.
 */
export function CoinChips({
  label,
  value,
  onChange,
  hisCoins,
  allCoins,
  placeholder,
  tone = "accent",
  disabled,
}: {
  label: string;
  value: string[];
  onChange: (next: string[]) => void;
  hisCoins: readonly string[];
  allCoins: readonly string[];
  placeholder?: string;
  tone?: "accent" | "danger";
  disabled?: boolean;
}) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const listId = useId();
  const known = [...hisCoins, ...allCoins];
  const sugg = open && !disabled ? suggestCoins(text, hisCoins, allCoins, value, 8) : [];
  const active = Math.min(hi, Math.max(0, sugg.length - 1));

  function add(coin: string) {
    const next = addCoin(value, coin, known);
    if (next.length !== value.length) onChange(next);
    setText("");
    setHi(0);
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown" && sugg.length) {
      e.preventDefault();
      setHi((active + 1) % sugg.length);
    } else if (e.key === "ArrowUp" && sugg.length) {
      e.preventDefault();
      setHi((active - 1 + sugg.length) % sugg.length);
    } else if (e.key === "Enter" || e.key === "," || (e.key === "Tab" && text.trim())) {
      if (!text.trim() && e.key !== "Enter") return;
      e.preventDefault();
      if (sugg.length && text.trim() && coinKey(sugg[active].coin).startsWith(coinKey(text))) add(sugg[active].coin);
      else if (text.trim()) add(text);
    } else if (e.key === "Backspace" && !text && value.length) {
      onChange(value.slice(0, -1));
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div className="relative">
      <div
        className={clsx(
          "flex min-h-9 flex-wrap items-center gap-1 rounded-lg border border-border bg-surface-2 px-2 py-1 focus-within:outline-2 focus-within:outline-[var(--focus-ring)]",
          disabled && "opacity-50",
        )}
      >
        {value.map((c) => (
          <span
            key={c}
            className={clsx(
              "font-num inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[11px] font-semibold",
              tone === "danger" ? "bg-danger/10 text-danger" : "bg-accent-soft text-accent",
            )}
          >
            {c}
            <button type="button" disabled={disabled} onClick={() => onChange(value.filter((x) => x !== c))} aria-label={`Remove ${c} from ${label}`} className="rounded hover:bg-black/10">
              <X size={11} aria-hidden="true" />
            </button>
          </span>
        ))}
        <input
          aria-label={label}
          role="combobox"
          aria-expanded={sugg.length > 0}
          aria-controls={listId}
          aria-autocomplete="list"
          disabled={disabled}
          value={text}
          placeholder={value.length ? "" : placeholder}
          onChange={(e) => {
            setText(e.target.value);
            setOpen(true);
            setHi(0);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 120)}
          onKeyDown={onKey}
          onPaste={(e) => {
            const t = e.clipboardData.getData("text");
            if (!/[\s,;]/.test(t.trim())) return;
            e.preventDefault();
            const next = parseCoins(t, known).reduce((acc, c) => addCoin(acc, c, known), value);
            onChange(next);
          }}
          className="min-w-[5rem] flex-1 bg-transparent py-0.5 text-sm outline-none placeholder:text-muted"
        />
      </div>
      {sugg.length ? (
        <ul id={listId} role="listbox" aria-label={`${label} suggestions`} className="absolute z-30 mt-1 max-h-52 w-full overflow-y-auto rounded-lg border border-border bg-surface py-1 shadow-lg">
          {sugg.map((s, i) => (
            <li
              key={s.coin}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => {
                e.preventDefault();
                add(s.coin);
              }}
              onMouseEnter={() => setHi(i)}
              className={clsx("flex cursor-pointer items-center justify-between px-3 py-1 text-sm", i === active && "bg-surface-2")}
            >
              <span className="font-num">{s.coin}</span>
              {s.his ? <span className="text-[10px] text-muted">he trades it</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
