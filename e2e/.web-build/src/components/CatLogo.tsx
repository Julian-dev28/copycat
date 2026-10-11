/**
 * The copycat mark: a cat head with pointed ears and two "copy" squares for
 * eyes (one offset behind the other, like a duplicate). Pure inline SVG that
 * takes `currentColor`, so it follows the accent and the theme. The same
 * geometry is in src/app/icon.svg (the favicon), so keep them in sync.
 */
export function CatLogo({ size = 24, className, title = "copycat" }: {
  size?: number;
  className?: string;
  title?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      role={title ? "img" : undefined}
      aria-label={title || undefined}
      aria-hidden={title ? undefined : true}
      className={className}
    >
      {title ? <title>{title}</title> : null}
      {/* head with two pointed ears */}
      <path
        d="M5 27V11.5L7.5 3.5L13 9h6l5.5-5.5L27 11.5V27a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2Z"
        fill="currentColor"
      />
      {/* eyes: a square with a copy behind it, each side */}
      <rect x="9.6" y="13.6" width="4.4" height="4.4" rx="0.9" fill="var(--cat-eye, #0b0b0c)" opacity="0.45" />
      <rect x="8.6" y="14.6" width="4.4" height="4.4" rx="0.9" fill="var(--cat-eye, #0b0b0c)" />
      <rect x="19.6" y="13.6" width="4.4" height="4.4" rx="0.9" fill="var(--cat-eye, #0b0b0c)" opacity="0.45" />
      <rect x="18.6" y="14.6" width="4.4" height="4.4" rx="0.9" fill="var(--cat-eye, #0b0b0c)" />
      {/* nose and whiskers */}
      <path d="M15 21.2h2l-1 1.3z" fill="var(--cat-eye, #0b0b0c)" />
      <path
        d="M3 20.5h4M3 23h4M25 20.5h4M25 23h4"
        stroke="var(--cat-eye, #0b0b0c)"
        strokeWidth="1.1"
        strokeLinecap="round"
        opacity="0.55"
      />
    </svg>
  );
}
