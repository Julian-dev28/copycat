import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { Providers } from "./providers";
import { TopNav } from "@/components/TopNav";
import { RevealObserver } from "@/components/shell/Reveal";
import { BottomTabBar } from "@/components/shell/BottomTabBar";
import { AppMain } from "@/components/shell/AppMain";
import { SettingsDrawer } from "@/components/SettingsDrawer";
import { PNL_BOOT_SCRIPT } from "@/lib/display/pnlMode";

// Self-hosted (latin subset, checked in under ./fonts, SIL OFL 1.1) so builds
// never depend on the network. Geist and Geist Mono are variable (100-900).
const geistSans = localFont({
  src: "./fonts/Geist-latin.woff2",
  variable: "--font-geist-sans",
  weight: "100 900",
  display: "swap",
});

const geistMono = localFont({
  src: "./fonts/GeistMono-latin.woff2",
  variable: "--font-geist-mono",
  weight: "100 900",
  display: "swap",
});

// Display accents only: one italic word in a page title or empty state (DESIGN 3.5).
const instrumentSerif = localFont({
  src: "./fonts/InstrumentSerif-Italic-latin.woff2",
  variable: "--font-instrument-serif",
  weight: "400",
  style: "italic",
  display: "swap",
});

export const metadata: Metadata = {
  title: "copycat",
  description: "Self-hosted Hyperliquid copy trading. Copy up to 25 traders with your own leverage and sizing.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#07080b" },
    { media: "(prefers-color-scheme: light)", color: "#f6f7f9" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} ${instrumentSerif.variable} h-full antialiased`}
      data-pnl="standard"
      suppressHydrationWarning
    >
      <head>
        {/* Applies the stored PnL color mode before first paint (no green/red flash for colorblind mode). */}
        <script dangerouslySetInnerHTML={{ __html: PNL_BOOT_SCRIPT }} />
      </head>
      <body className="flex min-h-full flex-col text-fg">
        <Providers>
          <a
            href="#main"
            className="sr-only z-[60] rounded-sm bg-accent text-sm font-medium text-accent-fg focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:px-4 focus:py-2"
          >
            Skip to content
          </a>
          <TopNav />
          <RevealObserver />
          <AppMain>{children}</AppMain>
          <BottomTabBar />
          <SettingsDrawer />
        </Providers>
      </body>
    </html>
  );
}
