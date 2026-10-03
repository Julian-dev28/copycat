/**
 * App-facing types, derived from the generated OpenAPI schema
 * (./schema.gen.ts, generated from services/api/openapi.json via
 * `npm run gen:api`). This is the thin layer that:
 *
 *   1. Re-exports the wire types under the same names contracts/models.py
 *      uses, so the rest of the app reads like the Python contract.
 *   2. Forces array/dict fields that have a pydantic default_factory
 *      (leaders, leader_overrides, positions, etc.) to be non-optional.
 *      FastAPI always serializes those defaults, so they're never
 *      actually missing on the wire — openapi-typescript marks them
 *      optional only because JSON Schema's `required` list reflects
 *      "has no default", not "always present in the response".
 *   3. Keeps SettingsPatch stricter than the wire contract: every
 *      field is a plain optional (never `| null`) except
 *      leader_overrides, because sending an explicit `null` for any
 *      other field is accepted by the schema but rejected by the api's
 *      re-validation through Settings (null isn't a valid Settings
 *      value for e.g. `enabled: bool`) -- see SettingsPatch's docstring
 *      in openapi.json. Narrowing it here makes that mistake a
 *      compile error instead of a 422 at runtime.
 *
 * If services/api's contract changes: re-run `npm run gen:api`, then
 * fix whatever breaks here (that's the point -- this file is the one
 * place drift between contracts/models.py and this app would surface).
 */
import type { components } from "./schema.gen";

type Schemas = components["schemas"];

export const CONTRACT_VERSION = 2;
export const MAX_LEADERS = 10;
export const HL_MIN_ORDER_USD = 10.5;
export const MAX_LEVERAGE_CAP = 50;

export type SizingMode = Schemas["SizingMode"];
export type LeverageMode = Schemas["LeverageMode"];
export type MarginMode = Schemas["MarginMode"];
export type Side = "long" | "short";

export type LeaderOverride = Schemas["LeaderOverride"];

export type Settings = Omit<Schemas["Settings"], "leaders" | "leader_overrides"> & {
  leaders: string[];
  leader_overrides: Record<string, LeaderOverride>;
};

/** PATCH body: see module doc point 3 for why this isn't just Partial<Schemas["SettingsPatch"]>. */
export type SettingsPatch = Partial<Omit<Settings, "leader_overrides">> & {
  leader_overrides?: Record<string, LeaderOverride | null>;
};

export type CopyPosition = Schemas["CopyPosition"];

export type EngineEventAction = Schemas["EngineEvent"]["action"];
export type EngineEvent = Schemas["EngineEvent"];

export type LeaderStatus = Omit<Schemas["LeaderStatus"], "owned_coins" | "effective"> & {
  owned_coins: string[];
  effective: Settings;
};

export type EngineStatus = Omit<Schemas["EngineStatus"], "leaders" | "positions"> & {
  leaders: LeaderStatus[];
  positions: CopyPosition[];
};

export type TraderScore = Omit<Schemas["TraderScore"], "coins" | "flags"> & {
  coins: string[];
  flags: string[];
};

export type DiscoveryRun = Omit<Schemas["DiscoveryRun"], "results" | "sim_settings"> & {
  results: TraderScore[];
  sim_settings: Settings;
};

export type HealthResponse = Schemas["HealthResponse"];

export type StartDiscoveryRunBody = Omit<Schemas["DiscoveryRunRequest"], "settings"> & {
  settings?: Settings;
};
