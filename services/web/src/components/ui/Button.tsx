import { clsx } from "clsx";
import type { ButtonHTMLAttributes } from "react";

/**
 * DESIGN.md 5 Buttons.
 * - primary: the one accent block per screen (accent bg, glow on hover).
 * - secondary: surface-2 + hairline. ghost: text only.
 * - danger: outline --danger at rest (Stop, Close all, Halt).
 * - danger-solid: filled --danger, only inside the confirm dialog.
 * Disabled: 40% opacity; pass `title` saying why ("Enter an amount").
 */
export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "danger-solid";
export type ButtonSize = "sm" | "md" | "lg";

export const BUTTON_VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-accent text-accent-fg border border-transparent hover:shadow-glow hover:brightness-105",
  secondary: "bg-surface-2 text-fg border border-border hover:bg-surface-3 hover:border-border-strong",
  ghost: "bg-transparent text-fg-soft border border-transparent hover:bg-surface-2 hover:text-fg",
  danger: "bg-transparent text-danger border border-danger/60 hover:bg-danger-soft hover:border-danger",
  "danger-solid": "bg-danger text-white border border-transparent hover:brightness-110 dark:text-[#1a0508]",
};

export const BUTTON_SIZE: Record<ButtonSize, string> = {
  sm: "h-8 text-xs px-3 rounded-sm gap-1.5",
  md: "h-9 text-sm px-4 rounded-sm gap-2",
  lg: "h-11 text-base px-5 rounded-xl gap-2",
};

/** The full class string, for links styled as buttons (<Link className={buttonClass("primary")}>). */
export function buttonClass(variant: ButtonVariant = "secondary", size: ButtonSize = "md", className?: string): string {
  return clsx(
    "inline-flex select-none items-center justify-center whitespace-nowrap font-medium cursor-pointer",
    "transition-[background-color,border-color,color,box-shadow,filter,scale] duration-[var(--dur-fast)] ease-out",
    "active:scale-[0.98] active:duration-[var(--dur-instant)]",
    "disabled:pointer-events-none disabled:opacity-40 aria-disabled:pointer-events-none aria-disabled:opacity-40",
    BUTTON_VARIANT[variant],
    BUTTON_SIZE[size],
    className,
  );
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export function Button({ variant = "secondary", size = "md", className, disabled, type = "button", ...rest }: ButtonProps) {
  return <button type={type} className={buttonClass(variant, size, className)} disabled={disabled} {...rest} />;
}
