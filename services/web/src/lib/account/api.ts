/**
 * Trading-account endpoints (contract v6), with two interchangeable sources:
 *   - liveAccounts: HTTP to services/api through apiFetch
 *   - demoAccounts (./demo.ts): an in-memory store for `?demo=1`
 * Same shapes both ways, so hooks and components never branch on mode.
 *
 * Calls that carry a secret (create, importKey, submit, refreshAgent,
 * transfer) go through here directly, never through useMutation: React
 * Query keeps mutation variables and results in its cache.
 */
import { apiFetch, ApiError } from "@/lib/api/client";
import { injectedProvider, type Eip1193Provider } from "./eip1193";
import { secretFetch } from "./secretFetch";
import type {
  AccountSummary, AgentApprovalPrepareRequest, AgentApprovalPrepareResponse, AgentApprovalSubmitRequest,
  CreateAccountRequest, CreateAccountResponse, HistoryKind, ImportApiKeyRequest, ImportEnvStatus, TradingAccount, TransferRequest,
} from "./types";

export interface AccountSource {
  list(): Promise<TradingAccount[]>;
  create(req: CreateAccountRequest): Promise<CreateAccountResponse>;
  importKey(req: ImportApiKeyRequest): Promise<TradingAccount>;
  importEnvStatus(): Promise<ImportEnvStatus>;
  importEnv(): Promise<TradingAccount[]>;
  prepare(req: AgentApprovalPrepareRequest): Promise<AgentApprovalPrepareResponse>;
  submit(req: AgentApprovalSubmitRequest): Promise<TradingAccount>;
  /** 409 while the current account still has engine copies; `force` leaves them unmanaged. */
  activate(id: string, force?: boolean): Promise<void>;
  rename(id: string, label: string): Promise<void>;
  remove(id: string): Promise<void>;
  refreshAgent(id: string, passphrase: string | null): Promise<void>;
  transfer(req: TransferRequest): Promise<void>;
  summary(id: string): Promise<AccountSummary>;
  history(id: string, kind: HistoryKind): Promise<unknown>;
  /** The wallet the sign flow talks to: window.ethereum live, a scripted fake in demo. */
  walletProvider(): Eip1193Provider | null;
}

function isAccount(x: unknown): x is TradingAccount {
  return Boolean(x && typeof x === "object" && "id" in x && "address" in x && "kind" in x);
}

/** Routes may answer with the account, {account}, or a list; take the account. */
export function asAccount(x: unknown): TradingAccount {
  if (isAccount(x)) return x;
  if (x && typeof x === "object" && "account" in x && isAccount((x as { account: unknown }).account)) return (x as { account: TradingAccount }).account;
  throw new ApiError(500, "the api returned something that is not a trading account");
}

export function asAccountList(x: unknown): TradingAccount[] {
  if (Array.isArray(x)) return x.filter(isAccount);
  if (x && typeof x === "object") {
    const o = x as { accounts?: unknown; account?: unknown };
    if (Array.isArray(o.accounts)) return o.accounts.filter(isAccount);
    if (isAccount(o.account)) return [o.account];
    if (isAccount(x)) return [x];
  }
  return [];
}

const post = (body?: unknown): RequestInit => ({ method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const enc = encodeURIComponent;

export const liveAccounts: AccountSource = {
  list: async () => asAccountList(await apiFetch<unknown>("/api/accounts")),
  create: (req) => apiFetch<CreateAccountResponse>("/api/accounts/create", post(req)),
  importKey: async (req) => asAccount(await apiFetch<unknown>("/api/accounts/import-key", post(req))),
  importEnvStatus: () => apiFetch<ImportEnvStatus>("/api/accounts/import-env"),
  importEnv: async () => asAccountList(await apiFetch<unknown>("/api/accounts/import-env", post())),
  prepare: (req) => apiFetch<AgentApprovalPrepareResponse>("/api/accounts/approve/prepare", post(req)),
  submit: async (req) => asAccount(await apiFetch<unknown>("/api/accounts/approve/submit", post(req))),
  activate: async (id, force = false) => {
    await apiFetch(`/api/accounts/${enc(id)}/activate${force ? "?force=true" : ""}`, post());
  },
  rename: async (id, label) => {
    await apiFetch(`/api/accounts/${enc(id)}`, { method: "PATCH", body: JSON.stringify({ label }) });
  },
  remove: async (id) => {
    await apiFetch(`/api/accounts/${enc(id)}`, { method: "DELETE" });
  },
  refreshAgent: async (id, passphrase) => {
    await secretFetch(`/api/accounts/${enc(id)}/refresh-agent`, passphrase ? { passphrase } : {});
  },
  transfer: async (req) => {
    await secretFetch("/api/accounts/transfer", req);
  },
  summary: (id) => apiFetch<AccountSummary>(`/api/accounts/${enc(id)}/summary`),
  history: (id, kind) => apiFetch<unknown>(`/api/accounts/${enc(id)}/history?kind=${kind}`),
  walletProvider: injectedProvider,
};
