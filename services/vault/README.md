# services/vault

The only owner of secrets in copycat. Public surface: `vault.public` (see its
docstring). Everything else in this package is internal.

    .venv/bin/python -m pytest services/vault            # gate, ~1s, no network
    .venv/bin/python -m pytest services/vault -m live    # eval: extraAgents read on mainnet

## Account kinds

| kind | how it gets in | what copycat stores |
|---|---|---|
| `created` | `create_account(label, passphrase)`: copycat generates the main wallet | main key sealed with your passphrase; an agent key sealed with the machine key |
| `connected_signed` | browser: the web generates an agent key, your wallet signs `approveAgent` (EIP-712), `submit_agent_approval` checks the signer and posts it to HL | agent key (machine key) |
| `connected_key` | you paste a main address + an API wallet key already approved at app.hyperliquid.xyz/API | agent key (machine key) |

Trading always signs with the AGENT key: it can trade, it cannot withdraw.
One vault account per main address: connecting the same wallet again replaces
its agent (HL replaces a same-name agent, so the old key is dead anyway).

## Storage: `$COPYCAT_DATA_DIR/vault/` (dir 0700, files 0600, atomic writes)

| file | content |
|---|---|
| `accounts.json` | `TradingAccount` rows (no secrets), `active_id`, `authoritative` |
| `machine.key` | 32 random bytes, created once (exclusive create, so racing processes share one) |
| `keys/<id>.agent.json` | agent private key, AES-256-GCM with `machine.key` |
| `keys/<id>.main.json` | created wallet's main key, AES-256-GCM with a key from scrypt(passphrase, n=2^15 r=8 p=1, random salt) |
| `removed/<id>.main.json` | a removed created wallet's sealed main key: archived, never deleted |
| `.lock` | flock for read-modify-write of `accounts.json` |

Every ciphertext is bound (GCM associated data) to its account id, purpose and
address: a blob copied onto another account fails to decrypt instead of
signing for the wrong wallet. A wrong passphrase, a tampered blob and a
foreign blob all fail with the same `invalid passphrase` (api: 401).

## Who trades: the active account

`active_credentials()` is what `hl.env` and the engine read every cycle. Until
the first `set_active`, the vault is not authoritative and `.env`
(`COPYCAT_ACCOUNT_ADDRESS` / `COPYCAT_AGENT_KEY`) keeps trading: creating or
connecting an account changes nothing by itself. From the first activation on
the vault decides, permanently: removing the active account stops trading,
it never falls back to `.env`. `import_env` (the web's one-click migration)
imports the `.env` pair as "Main (from .env)" and activates it, so trading
continues on the same wallet with the same key.

## Agent approval

- created: a fresh agent key, `approveAgent` signed by the main key through the
  SDK's own `sign_agent` (`hl.accounts.sign_approve_agent`), posted by
  `hl.accounts.post_signed_action`. No `Exchange` object: its constructor makes
  ~13 network reads an admin action does not need; the signed bytes are the same.
- browser: `prepare_agent_approval` returns `typed_data` (domain
  `HyperliquidSignTransaction` v1, `chainId` = `signatureChainId`, primary type
  `HyperliquidTransaction:ApproveAgent`, fields hyperliquidChain, agentAddress,
  agentName, nonce), the `action` and the `nonce`. `signatureChainId` is
  `0xa4b1` (Arbitrum One) on mainnet and `0x66eee` on testnet: MetaMask refuses
  typed data whose chainId differs from the wallet's chain, so the web switches
  chain first. `submit_agent_approval` rebuilds the typed data from the action
  (exact key set, approveAgent, our network, agentAddress == the submitted
  agent key's address, nonce under 15 minutes old), recovers the signer and
  requires it to be `main_address`, posts, then confirms through extraAgents
  (5 reads, 1 s apart).
- HL rejects `approveAgent` from an address it has never seen (no deposit):
  "User or API Wallet ... does not exist". That becomes `NeedsFunding` (409):
  "fund it first ..., then press Refresh agent". `create_account` still keeps
  the wallet (agent status `missing`) and says so in `backup_warning`.
- `refresh_agent`: created accounts sign a new approval with the passphrase;
  connected ones get 409 "re-run sign-in".

Agent status (`list_accounts`): extraAgents `validUntil`, cached 10 min per
address (a failed read 30 s): `active`, `expiring` (<= 30 days), `expired`,
`missing` (not stored, or HL no longer lists it), `unknown` (read failed).

## Transfers

`transfer(from_id, to_address, amount, passphrase, max_usd)`: `usdSend` of perps USDC,
signed by a created account's main key (passphrase required every time). The
destination must be another account in this vault: a stolen api token plus a
guessed passphrase still cannot send funds to an outside address.

## Funding: move, send, withdraw (`vault/funding.py`)

usdClassTransfer (spot <-> perps), usdSend and withdraw3 are user-signed:
only the MAIN key can sign them. Two paths, same guards:

- browser (connected accounts): `prepare_user_action` returns the action and
  its EIP-712 typed data (the SDK's own field lists, `hl.accounts.USER_ACTIONS`);
  the wallet signs; `submit_user_action` checks the exact key set, type, network,
  nonce (= time/nonce field, under 10 minutes old), amount string, rebuilds the
  canonical action, recovers the signer and requires it to be the account address.
- passphrase (created accounts): `run_user_action` unlocks the main key and signs
  through the SDK's `sign_*` function.

Guards: amount > 0 and <= `max_usd` (the live limit the api read; unknown ->
refused), withdraw > the 1 USDC fee, withdraw destination defaults to the
account itself and any other address needs `confirm_destination` equal to it,
usdSend only to another account in this vault (same rule as `transfer`, which
now delegates here), no spot/perps move on unified accounts.

`vault/audit.jsonl` (0600, appended under the vault lock): one line per attempt
that reached a guard, `{ts_ms, action, path, outcome ok|refused|rejected|error,
account_id, address, amount_usd, to_perp, destination, nonce, reason}`.
`audit.record` refuses any other field, so a signature, key or passphrase cannot
be logged by accident; reasons are VaultError messages (secret-free).

## Threat model, in plain words

- **Agent keys are encrypted with a key that sits next to them.** The engine
  must trade unattended, so it cannot ask for a passphrase. Anyone who can read
  `data/vault/` (your user account, root, a backup of the folder) can decrypt
  every agent key. That is the same exposure as the old `.env` file. What
  encryption buys: no plaintext key in `.env`, in the process environment, in a
  `cat`, a grep, a log, a screenshot or a pasted config. An agent key can trade
  your account into losses but cannot withdraw.
- **Main keys of created wallets need your passphrase.** A copy of the folder
  alone does not give them up; scrypt makes each guess cost ~0.1 s and 32 MB.
  A weak passphrase is still guessable offline: use a long one. The api
  rate-limits passphrase routes (5/min, 30/hour per route).
- **The api process handles secrets in flight.** Create, import, sign-in,
  refresh and transfer bodies carry keys or the passphrase; the api passes them
  to the vault and drops them. Python cannot wipe memory, so a heap dump of the
  api during a request could contain them. Nothing logs a body, and a 422 never
  echoes the input.
- **The main key of a created wallet is shown once.** If you lose that backup
  and the passphrase, the funds are gone. Removing the account archives the
  sealed key in `vault/removed/` instead of deleting it.
- **Not defended:** malware running as your user (it can read the vault and
  the machine key, or keylog the passphrase), a compromised browser during
  sign-in (it could swap the agent address before you sign; your wallet shows
  the agent address, check it), and a stolen api token used to activate or
  remove accounts (no funds move without the passphrase).
