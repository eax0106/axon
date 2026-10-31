import { execFileSync } from "node:child_process";
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
