/**
 * Throwaway copycat stack for the e2e lane.
 *
 *  - web: services/web copied into e2e/.web-build (so the operator's `next dev`
 *    on :3000 and its .next are never touched), built once per source hash +
 *    api URL, served with `next start` on a free port.
 *  - full mode adds: the mock Hyperliquid (e2e/mock_hl/server.py), the api,
 *    the engine (started as soon as a vault exists; it refuses to start with no
 *    account) and Scout, all on a fresh temp COPYCAT_DATA_DIR, with a generated
 *    token and every COPYCAT_* var from the parent shell dropped (no .env, no key).
 *
 * Never :3000 / :8787 / ./data. Every process is spawned in its own process
 * group so teardown kills the whole tree.
 */
import { spawn, spawnSync } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import * as fs from "node:fs";
import * as net from "node:net";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

export const E2E_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const REPO = path.resolve(E2E_DIR, "..");
export const STATE_FILE = path.join(E2E_DIR, ".stack.json");
const WEB_SRC = path.join(REPO, "services/web");
const WEB_BUILD = path.join(E2E_DIR, ".web-build");
const PY = process.env.E2E_PYTHON || path.join(REPO, ".venv/bin/python");
const FORBIDDEN_PORTS = new Set([3000, 8787]);
/** Preferred api port: the web build bakes the api URL in, so a stable port keeps the build cache warm. */
const PREFERRED_API_PORT = 18787;

export type StackMode = "web" | "full";

export interface StackState {
  mode: StackMode;
  root: string;
  dataDir: string;
  logsDir: string;
  webURL: string;
  apiURL: string;
  mockURL: string | null;
  token: string | null;
  pids: number[];
  startedMs: number;
}

export function readState(): StackState {
  return JSON.parse(fs.readFileSync(STATE_FILE, "utf8")) as StackState;
}

function log(msg: string) {
  process.stdout.write(`[e2e stack] ${msg}\n`);
}

async function portFree(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.once("error", () => resolve(false));
    srv.listen(port, "127.0.0.1", () => srv.close(() => resolve(true)));
  });
}

async function freePort(preferred?: number): Promise<number> {
  if (preferred && !FORBIDDEN_PORTS.has(preferred) && (await portFree(preferred))) return preferred;
  for (;;) {
    const port = await new Promise<number>((resolve, reject) => {
      const srv = net.createServer();
      srv.once("error", reject);
      srv.listen(0, "127.0.0.1", () => {
        const p = (srv.address() as net.AddressInfo).port;
        srv.close(() => resolve(p));
      });
    });
    if (!FORBIDDEN_PORTS.has(port)) return port;
  }
}

/** Hash of every file the web build depends on, plus the baked api URL. */
function webSourceHash(apiURL: string, srcDir: string): string {
  const h = createHash("sha256");
  h.update(apiURL);
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      if (["node_modules", ".next", "tsconfig.tsbuildinfo", "next-env.d.ts"].includes(e.name)) continue;
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else if (e.isFile()) {
        h.update(path.relative(srcDir, p));
        h.update(fs.readFileSync(p));
      }
    }
  };
  walk(srcDir);
  return h.digest("hex");
}

function run(cmd: string, args: string[], opts: { cwd: string; env?: NodeJS.ProcessEnv; logFile: string }) {
  const out = fs.openSync(opts.logFile, "a");
  const r = spawnSync(cmd, args, { cwd: opts.cwd, env: opts.env ?? process.env, stdio: ["ignore", out, out] });
  fs.closeSync(out);
  if (r.status !== 0) {
    throw new Error(`${cmd} ${args.join(" ")} failed (exit ${r.status}). Log: ${opts.logFile}\n${tail(opts.logFile)}`);
  }
}

function tail(file: string, n = 40): string {
  try {
    return fs.readFileSync(file, "utf8").split("\n").slice(-n).join("\n");
  } catch {
    return "(no log)";
  }
}

/** Copy services/web into e2e/.web-build and `next build` it unless the same sources were already built. */
export function buildWeb(apiURL: string, logsDir: string): void {
  if (!fs.existsSync(path.join(WEB_SRC, "node_modules"))) {
    throw new Error("services/web/node_modules is missing: run `make install` (or npm ci in services/web) first");
  }
  // E2E_WEB_REF=HEAD (or any git ref) builds the committed web instead of the working
  // tree: use it while another session has half-done edits in services/web.
  let srcDir = WEB_SRC;
  const ref = process.env.E2E_WEB_REF;
  if (ref) {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "copycat-e2e-src-"));
    const r = spawnSync("bash", ["-c", `git -C "${REPO}" archive "${ref}" services/web | tar -x -C "${tmp}"`]);
    if (r.status !== 0) throw new Error(`git archive ${ref} failed: ${r.stderr}`);
    srcDir = path.join(tmp, "services/web");
    log(`web source: git ${ref}`);
  }
  const hash = webSourceHash(apiURL, srcDir);
  const stamp = path.join(WEB_BUILD, ".e2e-build-hash");
  const logFile = path.join(logsDir, "web-build.log");
  if (process.env.E2E_REBUILD !== "1" && fs.existsSync(stamp) && fs.readFileSync(stamp, "utf8") === hash
      && fs.existsSync(path.join(WEB_BUILD, ".next/BUILD_ID"))) {
    log(`web build cached (${hash.slice(0, 10)})`);
    return;
  }
  const t0 = Date.now();
  fs.mkdirSync(WEB_BUILD, { recursive: true });
  run("rsync", ["-a", "--delete", "--exclude", "node_modules", "--exclude", ".next", "--exclude", ".e2e-build-hash",
    "--exclude", "tsconfig.tsbuildinfo", "--exclude", "next-env.d.ts", `${srcDir}/`, `${WEB_BUILD}/`],
    { cwd: REPO, logFile });
  // Turbopack refuses a node_modules symlink that leaves its root, so the copy's
  // root is the repo (which contains services/web/node_modules). The copy's own
  // next.config wraps the real one, so config changes in services/web still apply.
  // Tailwind's automatic source detection walks the gitignored copy and the
  // node_modules symlink (15 min and binary garbage classes). Pin it to src/,
  // which is where every class lives.
  const css = path.join(WEB_BUILD, "src/app/globals.css");
  const cssText = fs.readFileSync(css, "utf8");
  if (!cssText.startsWith('@import "tailwindcss";')) {
    throw new Error('services/web/src/app/globals.css no longer starts with @import "tailwindcss"; update e2e/harness/stack.ts');
  }
  fs.writeFileSync(css, cssText.replace('@import "tailwindcss";', '@import "tailwindcss" source("..");'));
  const nm = path.join(WEB_BUILD, "node_modules");
  if (!fs.existsSync(nm)) fs.symlinkSync(path.relative(WEB_BUILD, path.join(WEB_SRC, "node_modules")), nm);
  fs.renameSync(path.join(WEB_BUILD, "next.config.ts"), path.join(WEB_BUILD, "next.config.base.ts"));
  fs.writeFileSync(path.join(WEB_BUILD, "next.config.ts"), [
    `// generated by e2e/harness/stack.ts: services/web/next.config.ts + a turbopack root that contains node_modules`,
    `import type { NextConfig } from "next";`,
    `import base from "./next.config.base";`,
    `const config: NextConfig = { ...base, turbopack: { ...(base.turbopack ?? {}), root: ${JSON.stringify(REPO)} },`,
    `  outputFileTracingRoot: ${JSON.stringify(REPO)} };`,
    `export default config;`, ``].join("\n"));
  log(`building web (NEXT_PUBLIC_COPYCAT_API=${apiURL}) ...`);
  run(path.join(WEB_BUILD, "node_modules/.bin/next"), ["build"], {
    cwd: WEB_BUILD, logFile,
    env: { ...process.env, NEXT_PUBLIC_COPYCAT_API: apiURL, NEXT_TELEMETRY_DISABLED: "1" },
  });
  fs.writeFileSync(stamp, hash);
  log(`web built in ${((Date.now() - t0) / 1000).toFixed(1)}s`);
}

/** Environment for the python services: nothing COPYCAT_* inherited from the shell (it may hold the real key). */
function pyEnv(extra: Record<string, string>): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {};
  for (const [k, v] of Object.entries(process.env)) {
    if (k.startsWith("COPYCAT_") || k === "PYTHONPATH" || k === "VIRTUAL_ENV") continue;
    env[k] = v;
  }
  return {
    ...env,
    PYTHONPATH: [".", "services/hl", "services/vault", "services/engine", "services/discovery", "services/api"]
      .map((p) => path.join(REPO, p)).join(":"),
    PYTHONUNBUFFERED: "1",
    COPYCAT_SKIP_DOTENV: "1",
    ...extra,
  };
}

function launch(name: string, cmd: string, args: string[], opts: { cwd: string; env: NodeJS.ProcessEnv; logsDir: string }): number {
  const out = fs.openSync(path.join(opts.logsDir, `${name}.log`), "a");
  const child = spawn(cmd, args, { cwd: opts.cwd, env: opts.env, detached: true, stdio: ["ignore", out, out] });
  child.unref();
  fs.closeSync(out);
  if (!child.pid) throw new Error(`could not start ${name}`);
  log(`${name} started (pid ${child.pid})`);
  return child.pid;
}

async function waitFor(name: string, url: string, logFile: string, timeoutMs = 90_000, init?: RequestInit): Promise<void> {
  const t0 = Date.now();
  let last = "";
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await fetch(url, init);
      if (r.ok) return;
      last = `HTTP ${r.status}`;
    } catch (e) {
      last = String(e);
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`${name} not ready at ${url} after ${timeoutMs}ms (${last}). Log ${logFile}:\n${tail(logFile)}`);
}

export function killAll(pids: number[]): void {
  for (const pid of pids) {
    try { process.kill(-pid, "SIGTERM"); } catch { /* gone */ }
  }
  const deadline = Date.now() + 5000;
  for (const pid of pids) {
    while (Date.now() < deadline) {
      try { process.kill(-pid, 0); } catch { break; }
      spawnSync("sleep", ["0.1"]);
    }
    try { process.kill(-pid, "SIGKILL"); } catch { /* gone */ }
  }
}

export async function startStack(mode: StackMode): Promise<StackState> {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "copycat-e2e-"));
  const dataDir = path.join(root, "data");
  const logsDir = path.join(root, "logs");
  fs.mkdirSync(dataDir, { recursive: true });
  fs.mkdirSync(logsDir, { recursive: true });
  const realData = path.join(REPO, "data");
  if (path.resolve(dataDir).startsWith(path.resolve(realData))) throw new Error("refusing: temp data dir inside ./data");

  const apiPort = await freePort(PREFERRED_API_PORT);
  const webPort = await freePort();
  for (const p of [apiPort, webPort]) if (FORBIDDEN_PORTS.has(p)) throw new Error(`refusing port ${p}`);
  const apiURL = `http://localhost:${apiPort}`;
  const webURL = `http://localhost:${webPort}`;
  const state: StackState = { mode, root, dataDir, logsDir, webURL, apiURL, mockURL: null, token: null, pids: [],
    startedMs: Date.now() };
  log(`root ${root}  (logs: ${logsDir})`);

  try {
    buildWeb(apiURL, logsDir);
    if (mode === "full") {
      const mockPort = await freePort();
      state.mockURL = `http://127.0.0.1:${mockPort}`;
      const token = randomBytes(32).toString("hex");
      state.token = token;
      const env = pyEnv({
        COPYCAT_DATA_DIR: dataDir,
        COPYCAT_ENV_FILE: path.join(root, "no-such.env"),   // import-env never reads the repo's .env
        COPYCAT_HL_BASE_URL: state.mockURL,
        COPYCAT_API_TOKEN: token,
        COPYCAT_API_PORT: String(apiPort),
        COPYCAT_BIND: "127.0.0.1",
        COPYCAT_WEB_ORIGIN: webURL,
        COPYCAT_MCP_ALLOW_TRADING: "1",
        COPYCAT_HL_RATE_CAPACITY: "1000000",
        COPYCAT_HL_RATE_REFILL_PER_SEC: "1000000",
        COPYCAT_HL_TIMEOUT_S: "5",
        COPYCAT_LOG_LEVEL: "INFO",
      });
      state.pids.push(launch("mock_hl", PY, [path.join(E2E_DIR, "mock_hl/server.py"), "--port", String(mockPort)],
        { cwd: REPO, env, logsDir }));
      await waitFor("mock_hl", `${state.mockURL}/__mock/health`, path.join(logsDir, "mock_hl.log"));
      state.pids.push(launch("api", PY, ["-m", "api"], { cwd: REPO, env, logsDir }));
      // The engine exits when there is neither a vault nor COPYCAT_ACCOUNT_ADDRESS: start it once the
      // test has imported an account (the vault file appears), exactly like a first-time user.
      state.pids.push(launch("engine", "bash", ["-c",
        `until [ -f "$COPYCAT_DATA_DIR/vault/accounts.json" ]; do sleep 0.3; done; exec "${PY}" -m engine`],
        { cwd: REPO, env, logsDir }));
      if (process.env.E2E_SCOUT !== "0") {
        state.pids.push(launch("scout", PY, ["-m", "discovery.scout", "serve"],
          { cwd: REPO, env: { ...env, COPYCAT_HL_PRIORITY: "background" }, logsDir }));
      }
      await waitFor("api", `${apiURL}/api/health`, path.join(logsDir, "api.log"));
    }
    state.pids.push(launch("web", path.join(WEB_BUILD, "node_modules/.bin/next"),
      ["start", "-p", String(webPort), "-H", "localhost"],
      { cwd: WEB_BUILD, env: { ...process.env, NEXT_TELEMETRY_DISABLED: "1", PORT: String(webPort) }, logsDir }));
    await waitFor("web", `${webURL}/?demo=1`, path.join(logsDir, "web.log"));
  } catch (e) {
    killAll(state.pids);
    throw e;
  }
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
  log(`${mode} stack up: web ${webURL}  api ${apiURL}${state.mockURL ? `  mock ${state.mockURL}` : ""}`);
  return state;
}

export function stopStack(): void {
  if (!fs.existsSync(STATE_FILE)) return;
  const st = readState();
  killAll(st.pids);
  fs.rmSync(STATE_FILE, { force: true });
  if (process.env.E2E_KEEP !== "1") fs.rmSync(st.root, { recursive: true, force: true });
  else log(`kept ${st.root}`);
}
