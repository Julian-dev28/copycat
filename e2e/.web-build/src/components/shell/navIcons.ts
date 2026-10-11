import { BarChart3, CircleUserRound, Settings, Telescope, Wallet, type LucideIcon } from "lucide-react";
import type { NavHref } from "@/lib/shell/nav";

export const NAV_ICONS: Record<NavHref, LucideIcon> = {
  "/": BarChart3,
  "/scout": Telescope,
  "/portfolio": Wallet,
  "/account": CircleUserRound,
  "/settings": Settings,
};
