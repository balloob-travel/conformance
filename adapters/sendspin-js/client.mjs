#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

function parseArgs(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || value === undefined) {
      throw new Error(`Invalid arguments near ${key ?? "<eof>"}`);
    }
    values[key.slice(2)] = value;
  }
  return values;
}

function writeJson(filePath, payload) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

const args = parseArgs(process.argv.slice(2));
const summary = {
  status: "error",
  implementation: "sendspin-js",
  role: "client",
  reason:
    args["failure-reason"] ??
    "sendspin-js client conformance is intentionally disabled until the adapter can use the public SDK like an example application, without bespoke protocol code.",
  scenario_id: args["scenario-id"] ?? null,
  initiator_role: args["initiator-role"] ?? null,
  preferred_codec: args["preferred-codec"] ?? null,
  client_id: args["client-id"] ?? null,
  client_name: args["client-name"] ?? null,
  peer_hello: null,
};

writeJson(args.ready, {
  status: "ready",
  implementation: "sendspin-js",
  scenario_id: args["scenario-id"] ?? null,
  initiator_role: args["initiator-role"] ?? null,
});
writeJson(args.summary, summary);
process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
process.exit(1);
