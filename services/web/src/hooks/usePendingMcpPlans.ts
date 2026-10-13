"use client";

import { useQuery } from "@tanstack/react-query";
import { api, isNotSupported } from "@/lib/api/client";
import { useAuth } from "@/context/AuthContext";

/** Live MCP plans with their confirm codes. Polled; off in demo mode and without a token. */
export function usePendingMcpPlans(enabled: boolean) {
  const { hasToken } = useAuth();
  return useQuery({
    queryKey: ["mcp-plans-pending"],
    queryFn: api.getPendingMcpPlans,
    enabled: enabled && hasToken,
    refetchInterval: (q) => (isNotSupported(q.state.error) ? false : 3000),
    retry: (n, err) => !isNotSupported(err) && n < 2,
  });
}
