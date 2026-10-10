import type { Metadata } from "next";
import { Suspense } from "react";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import { TopNav } from "@/components/TopNav";
import { SettingsDrawer } from "@/components/SettingsDrawer";
import { DemoStrip } from "@/components/DemoStrip";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "copycat",
  description: "Self-hosted Hyperliquid copy trading. Mirror up to 25 wallets with your own leverage and sizing.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <Providers>
          <TopNav />
          <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
            <Suspense fallback={null}>
              <DemoStrip />
            </Suspense>
            {children}
          </main>
          <SettingsDrawer />
        </Providers>
      </body>
    </html>
  );
}
