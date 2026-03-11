#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

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

function hexSha256(buffer) {
  return crypto.createHash("sha256").update(buffer).digest("hex");
}

class FloatPcmHasher {
  constructor() {
    this.hash = crypto.createHash("sha256");
    this.sampleCount = 0;
  }

  updateFromPcmBytes(buffer, bitDepth) {
    if (bitDepth === 16) {
      for (let offset = 0; offset + 2 <= buffer.length; offset += 2) {
        const sample = buffer.readInt16LE(offset) / 32768;
        const bytes = Buffer.allocUnsafe(4);
        bytes.writeFloatLE(sample, 0);
        this.hash.update(bytes);
        this.sampleCount += 1;
      }
      return;
    }
    if (bitDepth === 24) {
      for (let offset = 0; offset + 3 <= buffer.length; offset += 3) {
        let value =
          buffer[offset] |
          (buffer[offset + 1] << 8) |
          (buffer[offset + 2] << 16);
        if (value & 0x800000) {
          value |= ~0xffffff;
        }
        const bytes = Buffer.allocUnsafe(4);
        bytes.writeFloatLE(value / 8388608, 0);
        this.hash.update(bytes);
        this.sampleCount += 1;
      }
      return;
    }
    if (bitDepth === 32) {
      for (let offset = 0; offset + 4 <= buffer.length; offset += 4) {
        const sample = buffer.readInt32LE(offset) / 2147483648;
        const bytes = Buffer.allocUnsafe(4);
        bytes.writeFloatLE(sample, 0);
        this.hash.update(bytes);
        this.sampleCount += 1;
      }
      return;
    }
    throw new Error(`Unsupported PCM bit depth: ${bitDepth}`);
  }

  hexdigest() {
    return this.hash.copy().digest("hex");
  }
}

async function waitForServerUrl(registryPath, serverName, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const payload = JSON.parse(fs.readFileSync(registryPath, "utf8"));
      const url = payload?.[serverName]?.url;
      if (typeof url === "string" && url.length > 0) {
        return url;
      }
    } catch {
      // Ignore partial writes while the server is starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out waiting for server "${serverName}"`);
}

function locateSendspinJsRepo() {
  const explicit = process.env.CONFORMANCE_REPO_SENDSPIN_JS;
  if (explicit) {
    return explicit;
  }
  const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..", "..");
  const reposPath = path.join(repoRoot, "repos", "sendspin-js");
  if (fs.existsSync(reposPath)) {
    return reposPath;
  }
  return path.resolve(repoRoot, "..", "sendspin-js");
}

function installNodeBrowserShims() {
  globalThis.window ??= globalThis;
  globalThis.self ??= globalThis;
  if (typeof globalThis.window.isSecureContext === "undefined") {
    globalThis.window.isSecureContext = true;
  }
}

class Deferred {
  constructor() {
    this.settled = false;
    this.promise = new Promise((resolve, reject) => {
      this.resolve = (value) => {
        if (!this.settled) {
          this.settled = true;
          resolve(value);
        }
      };
      this.reject = (error) => {
        if (!this.settled) {
          this.settled = true;
          reject(error);
        }
      };
    });
  }
}

const args = parseArgs(process.argv.slice(2));

if ((args["initiator-role"] ?? "client") !== "client") {
  const summary = {
    status: "error",
    implementation: "sendspin-js",
    role: "client",
    reason: "sendspin-js client adapter only supports client-initiated scenarios",
    scenario_id: args["scenario-id"] ?? null,
    initiator_role: args["initiator-role"] ?? null,
    preferred_codec: args["preferred-codec"] ?? null,
    client_name: args["client-name"] ?? null,
    client_id: args["client-id"] ?? null,
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
}

installNodeBrowserShims();

const repoPath = locateSendspinJsRepo();
const distPath = path.join(repoPath, "dist");
const protocolModule = await import(
  pathToFileURL(path.join(distPath, "protocol-handler.js")).href
);
const stateModule = await import(
  pathToFileURL(path.join(distPath, "state-manager.js")).href
);
const timeFilterModule = await import(
  pathToFileURL(path.join(distPath, "time-filter.js")).href
);
const websocketModule = await import(
  pathToFileURL(path.join(distPath, "websocket-manager.js")).href
);

const { ProtocolHandler } = protocolModule;
const { StateManager } = stateModule;
const { SendspinTimeFilter } = timeFilterModule;
const { WebSocketManager } = websocketModule;

const disconnectSignal = new Deferred();
const receivedHasher = new FloatPcmHasher();
let encodedBuffers = [];
let peerHello = null;
let currentStream = null;
let chunkCount = 0;
let failureReason = null;
let sawStreamEnd = false;

class HarnessAudioProcessor {
  initAudioContext() {}
  resumeAudioContext() {}
  clearBuffers() {}
  startAudioElement() {}
  stopAudioElement() {}
  updateVolume() {}
  close() {}

  handleBinaryMessage(data) {
    const frame = Buffer.from(data);
    if (frame.length < 9) {
      throw new Error(`Binary frame too short: ${frame.length}`);
    }
    if (frame[0] !== 0x04) {
      return;
    }
    if (!currentStream) {
      throw new Error("Received audio before stream/start");
    }
    if (currentStream.codec !== "pcm") {
      throw new Error(`Unsupported codec for second scenario: ${currentStream.codec}`);
    }
    const payload = frame.subarray(9);
    encodedBuffers.push(payload);
    receivedHasher.updateFromPcmBytes(payload, currentStream.bit_depth ?? 16);
    chunkCount += 1;
  }
}

const stateManager = new StateManager(() => {});
const timeFilter = new SendspinTimeFilter(0, 1.1, 2.0, 1e-12);
const wsManager = new WebSocketManager();
const audioProcessor = new HarnessAudioProcessor();
const protocolHandler = new ProtocolHandler(
  args["client-id"],
  wsManager,
  audioProcessor,
  stateManager,
  timeFilter,
  {
    clientName: args["client-name"],
    codecs: ["pcm"],
    bufferCapacity: 2_000_000,
    useHardwareVolume: false,
    useOutputLatencyCompensation: false,
  },
);

protocolHandler.getSupportedFormats = () => [
  {
    codec: "pcm",
    sample_rate: 8000,
    channels: 1,
    bit_depth: 16,
  },
];

writeJson(args.ready, {
  status: "ready",
  scenario_id: args["scenario-id"],
  initiator_role: args["initiator-role"],
});

const timeoutMs = Number(args["timeout-seconds"] ?? "30") * 1000;

try {
  const serverUrl = await waitForServerUrl(
    args.registry,
    args["server-name"],
    timeoutMs,
  );

  await wsManager.connect(
    serverUrl,
    () => {
      protocolHandler.sendClientHello();
    },
    (event) => {
      try {
        if (typeof event.data === "string") {
          const message = JSON.parse(event.data);
          if (message?.type === "server/hello") {
            peerHello = message;
          }
          if (message?.type === "stream/start") {
            currentStream = message.payload?.player ?? null;
          }
          if (message?.type === "stream/end") {
            sawStreamEnd = true;
          }
        }
        protocolHandler.handleMessage(event);
        if (sawStreamEnd) {
          protocolHandler.stopTimeSync();
          stateManager.clearAllIntervals();
          wsManager.disconnect();
          disconnectSignal.resolve();
        }
      } catch (error) {
        failureReason = error instanceof Error ? error.message : String(error);
        wsManager.disconnect();
        disconnectSignal.reject(error);
      }
    },
    (error) => {
      failureReason = error?.message ?? "WebSocket error";
      disconnectSignal.reject(new Error(failureReason));
    },
    () => {
      protocolHandler.stopTimeSync();
      stateManager.clearAllIntervals();
      wsManager.disconnect();
      disconnectSignal.resolve();
    },
  );

  await Promise.race([
    disconnectSignal.promise,
    new Promise((_, reject) =>
      setTimeout(() => reject(new Error("Timed out waiting for server disconnect")), timeoutMs),
    ),
  ]);
} catch (error) {
  failureReason = error instanceof Error ? error.message : String(error);
}

audioProcessor.close();
stateManager.clearAllIntervals();

const summary =
  failureReason === null
    ? {
        status: "ok",
        implementation: "sendspin-js",
        role: "client",
        scenario_id: args["scenario-id"],
        initiator_role: args["initiator-role"],
        preferred_codec: args["preferred-codec"],
        client_name: args["client-name"],
        client_id: args["client-id"],
        peer_hello: peerHello,
        server: peerHello?.payload ?? null,
        stream: currentStream,
        audio: {
          audio_chunk_count: chunkCount,
          received_encoded_sha256: hexSha256(Buffer.concat(encodedBuffers)),
          received_pcm_sha256: receivedHasher.hexdigest(),
          received_sample_count: receivedHasher.sampleCount,
        },
      }
    : {
        status: "error",
        implementation: "sendspin-js",
        role: "client",
        reason: failureReason,
        scenario_id: args["scenario-id"],
        initiator_role: args["initiator-role"],
        preferred_codec: args["preferred-codec"],
        client_name: args["client-name"],
        client_id: args["client-id"],
        peer_hello: peerHello,
        server: peerHello?.payload ?? null,
        stream: currentStream,
        audio: {
          audio_chunk_count: chunkCount,
          received_encoded_sha256:
            chunkCount > 0 ? hexSha256(Buffer.concat(encodedBuffers)) : null,
          received_pcm_sha256:
            chunkCount > 0 ? receivedHasher.hexdigest() : null,
          received_sample_count: receivedHasher.sampleCount,
        },
      };

writeJson(args.summary, summary);
process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
process.exit(failureReason === null ? 0 : 1);
