import { execFileSync } from "node:child_process";
import { createHmac } from "node:crypto";
import { fileURLToPath } from "node:url";

// The Compose stack the tests run against (COMPOSE_PROJECT_NAME is honoured from the environment).
const compose = ["compose", "-f", fileURLToPath(new URL("../../../deploy/docker-compose.yml", import.meta.url))];
const exec = (service: string, args: string[]) =>
  execFileSync("docker", [...compose, "exec", "-T", service, ...args], { encoding: "utf8" }).trim();

/** One SQL statement as the database owner; returns the first column of the first row. */
export const sql = (query: string) => exec("postgres", ["psql", "-U", "axon", "-d", "axon", "-Atc", query]).split("\n")[0] ?? "";

/** Publish on a call's live channel exactly as the engine does (engine/events.py redis_sink). */
export const publish = (callId: string, event: Record<string, unknown>) =>
  exec("redis", ["redis-cli", "PUBLISH", `call:${callId}:events`, JSON.stringify({ at: Date.now() / 1000, ...event })]);

/** The code an authenticator app shows now for a base32 key (RFC 6238: SHA-1, 6 digits, 30 s). */
export function totp(key: string, at = Date.now()): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const c of key.replace(/\s/g, "").toUpperCase()) bits += alphabet.indexOf(c).toString(2).padStart(5, "0");
  const bytes = Buffer.from((bits.match(/.{8}/g) ?? []).map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 30000)));
  const mac = createHmac("sha1", bytes).update(counter).digest();
  const offset = mac[mac.length - 1]! & 0x0f;
  return String((mac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}
