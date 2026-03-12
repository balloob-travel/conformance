#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

import { WebSocketServer } from "ws";

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

function registerEndpoint(registryPath, clientName, url) {
  let payload = {};
  try {
    payload = JSON.parse(fs.readFileSync(registryPath, "utf8"));
  } catch {
    payload = {};
  }
  payload[clientName] = { url };
  writeJson(registryPath, payload);
}

function hexSha256(buffer) {
  return crypto.createHash("sha256").update(buffer).digest("hex");
}

function isPlayerScenario(scenarioId) {
  return (
    scenarioId === "client-initiated-pcm" ||
    scenarioId === "server-initiated-pcm" ||
    scenarioId === "server-initiated-flac"
  );
}

function isMetadataScenario(scenarioId) {
  return (
    scenarioId === "client-initiated-metadata" ||
    scenarioId === "server-initiated-metadata"
  );
}

function isControllerScenario(scenarioId) {
  return (
    scenarioId === "client-initiated-controller" ||
    scenarioId === "server-initiated-controller"
  );
}

function isArtworkScenario(scenarioId) {
  return (
    scenarioId === "client-initiated-artwork" ||
    scenarioId === "server-initiated-artwork"
  );
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
  const repoRoot = path.resolve(
    path.dirname(new URL(import.meta.url).pathname),
    "..",
    "..",
  );
  const reposPath = path.join(repoRoot, "repos", "sendspin-js");
  if (fs.existsSync(reposPath)) {
    return reposPath;
  }
  return path.resolve(repoRoot, "..", "sendspin-js");
}

function installNodeBrowserShims() {
  globalThis.window ??= globalThis;
  globalThis.self ??= globalThis;
  globalThis.navigator ??= {
    vendor: "Node.js",
    userAgent: `Node.js ${process.version}`,
  };
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

function supportedRolesForScenario(scenarioId) {
  if (isMetadataScenario(scenarioId)) {
    return ["metadata@v1"];
  }
  if (isControllerScenario(scenarioId)) {
    return ["controller@v1"];
  }
  if (isArtworkScenario(scenarioId)) {
    return ["artwork@v1"];
  }
  return ["player@v1"];
}

function buildClientHello(args, scenarioId) {
  const hello = {
    type: "client/hello",
    payload: {
      client_id: args["client-id"],
      name: args["client-name"],
      version: 1,
      supported_roles: supportedRolesForScenario(scenarioId),
      device_info: {
        product_name: "sendspin-js Conformance Client",
        manufacturer: "Sendspin Conformance",
        software_version: "0.1.0",
      },
    },
  };
  if (isArtworkScenario(scenarioId)) {
    hello.payload["artwork@v1_support"] = {
      channels: [
        {
          source: "album",
          format: args["artwork-format"] ?? "jpeg",
          media_width: Number(args["artwork-width"] ?? "256"),
          media_height: Number(args["artwork-height"] ?? "256"),
        },
      ],
    };
    return hello;
  }
  if (isPlayerScenario(scenarioId)) {
    hello.payload["player@v1_support"] = {
      supported_formats:
        (args["preferred-codec"] ?? "flac") === "pcm"
          ? [
              {
                codec: "pcm",
                sample_rate: 8000,
                channels: 1,
                bit_depth: 16,
              },
            ]
          : [
              {
                codec: "flac",
                sample_rate: 8000,
                channels: 1,
                bit_depth: 16,
              },
              {
                codec: "pcm",
                sample_rate: 8000,
                channels: 1,
                bit_depth: 16,
              },
            ],
      buffer_capacity: 2_000_000,
      supported_commands: ["volume", "mute"],
    };
  }
  return hello;
}

function normalizeMetadata(metadata) {
  if (!metadata) {
    return null;
  }
  return {
    title: metadata.title ?? null,
    artist: metadata.artist ?? null,
    album_artist: metadata.album_artist ?? null,
    album: metadata.album ?? null,
    artwork_url: metadata.artwork_url ?? null,
    year: metadata.year ?? null,
    track: metadata.track ?? null,
    repeat: metadata.repeat ?? null,
    shuffle: metadata.shuffle ?? null,
    progress: metadata.progress
      ? {
          track_progress: metadata.progress.track_progress ?? null,
          track_duration: metadata.progress.track_duration ?? null,
          playback_speed: metadata.progress.playback_speed ?? null,
        }
      : null,
  };
}

function normalizeController(controller) {
  if (!controller) {
    return null;
  }
  return {
    supported_commands: controller.supported_commands ?? [],
    volume: controller.volume ?? null,
    muted: controller.muted ?? null,
  };
}

class HarnessAudioProcessor {
  constructor(onPcmChunk) {
    this.onPcmChunk = onPcmChunk;
  }

  initAudioContext() {}

  resumeAudioContext() {}

  clearBuffers() {}

  startAudioElement() {}

  stopAudioElement() {}

  updateVolume() {}

  close() {}

  handleBinaryMessage(data) {
    const frame = Buffer.from(data);
    if (frame.length < 9 || frame[0] !== 0x04) {
      return;
    }
    const payload = frame.subarray(9);
    this.onPcmChunk(payload);
  }
}

class AttachedWebSocketManager {
  constructor() {
    this.socket = null;
    this.onOpenHandler = null;
    this.onMessageHandler = null;
    this.onErrorHandler = null;
    this.onCloseHandler = null;
  }

  async attach(socket, onOpen, onMessage, onError, onClose) {
    this.socket = socket;
    this.onOpenHandler = onOpen;
    this.onMessageHandler = onMessage;
    this.onErrorHandler = onError;
    this.onCloseHandler = onClose;

    socket.on("message", (data, isBinary) => {
      if (!this.onMessageHandler) {
        return;
      }
      if (isBinary) {
        const buffer = Buffer.from(data);
        const arrayBuffer = buffer.buffer.slice(
          buffer.byteOffset,
          buffer.byteOffset + buffer.byteLength,
        );
        this.onMessageHandler({ data: arrayBuffer });
        return;
      }
      this.onMessageHandler({ data: data.toString() });
    });
    socket.on("error", (error) => {
      if (this.onErrorHandler) {
        this.onErrorHandler(error);
      }
    });
    socket.on("close", () => {
      this.socket = null;
      if (this.onCloseHandler) {
        this.onCloseHandler();
      }
    });
    if (this.onOpenHandler) {
      this.onOpenHandler();
    }
  }

  disconnect() {
    if (this.socket) {
      this.socket.close();
      this.socket = null;
    }
  }

  send(message) {
    if (this.socket && this.socket.readyState === 1) {
      this.socket.send(JSON.stringify(message));
    }
  }

  isConnected() {
    return this.socket !== null && this.socket.readyState === 1;
  }

  getReadyState() {
    return this.socket?.readyState ?? 3;
  }
}

const args = parseArgs(process.argv.slice(2));
const scenarioId = args["scenario-id"] ?? "client-initiated-pcm";
const initiatorRole = args["initiator-role"] ?? "client";
const timeoutMs = Number(args["timeout-seconds"] ?? "30") * 1000;

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
const stateManager = new StateManager(() => {});
const timeFilter = new SendspinTimeFilter(0, 1.1, 2.0, 1e-12);
const transportManager =
  initiatorRole === "client" ? new WebSocketManager() : new AttachedWebSocketManager();

let peerHello = null;
let currentStream = null;
let encodedBuffers = [];
let chunkCount = 0;
let failureReason = null;
let metadataState = {
  updateCount: 0,
  received: null,
};
let controllerState = {
  receivedState: null,
  sentCommand: null,
};
let artworkState = {
  stream: null,
  channel: null,
  receivedCount: 0,
  receivedSha256: null,
  byteCount: 0,
};
const artworkHasher = crypto.createHash("sha256");

const audioProcessor = new HarnessAudioProcessor((payload) => {
  if (!currentStream) {
    throw new Error("Received audio before stream/start");
  }
  encodedBuffers.push(payload);
  chunkCount += 1;
  if (currentStream.codec === "pcm") {
    receivedHasher.updateFromPcmBytes(payload, currentStream.bit_depth ?? 16);
    return;
  }
  if (currentStream.codec === "flac") {
    return;
  }
  throw new Error(`Unsupported codec for current scenario: ${currentStream.codec}`);
});

const protocolHandler = new ProtocolHandler(
  args["client-id"],
  transportManager,
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
    codec:
      scenarioId === "server-initiated-flac"
        ? args["preferred-codec"] ?? "flac"
        : "pcm",
    sample_rate: 8000,
    channels: 1,
    bit_depth: 16,
  },
];

protocolHandler.sendClientHello = () => {
  transportManager.send(buildClientHello(args, scenarioId));
};

function stopProtocolTimers() {
  try {
    protocolHandler.stopTimeSync();
  } catch {
    // Best-effort cleanup.
  }
  stateManager.clearAllIntervals();
}

function failConnection(error) {
  failureReason = error instanceof Error ? error.message : String(error);
  transportManager.disconnect();
  disconnectSignal.reject(new Error(failureReason));
}

function handleMessage(event) {
  try {
    if (typeof event.data === "string") {
      const message = JSON.parse(event.data);
      if (message?.type === "server/hello") {
        peerHello = message;
      }
      if (message?.type === "server/state") {
        if (message.payload?.metadata) {
          metadataState.updateCount += 1;
          metadataState.received = normalizeMetadata(message.payload.metadata);
        }
        if (message.payload?.controller) {
          controllerState.receivedState = normalizeController(
            message.payload.controller,
          );
          const supported =
            controllerState.receivedState?.supported_commands ?? [];
          if (
            isControllerScenario(scenarioId) &&
            controllerState.sentCommand === null &&
            supported.includes(args["controller-command"] ?? "next")
          ) {
            controllerState.sentCommand = {
              command: args["controller-command"] ?? "next",
            };
            protocolHandler.sendCommand(
              args["controller-command"] ?? "next",
              {},
            );
          }
        }
      }
      if (message?.type === "stream/start") {
        currentStream = message.payload?.player ?? null;
        if (message.payload?.artwork) {
          artworkState.stream = message.payload.artwork;
        }
      }
      if (isPlayerScenario(scenarioId)) {
        protocolHandler.handleMessage(event);
      }
      return;
    }

    const frame = Buffer.from(event.data);
    if (frame.length < 9) {
      return;
    }

    if (isArtworkScenario(scenarioId) && frame[0] >= 0x08 && frame[0] <= 0x0b) {
      const payload = frame.subarray(9);
      artworkState.channel = frame[0] - 0x08;
      artworkState.receivedCount += 1;
      artworkState.byteCount += payload.length;
      artworkHasher.update(payload);
      artworkState.receivedSha256 = artworkHasher.copy().digest("hex");
      return;
    }

    if (isPlayerScenario(scenarioId)) {
      protocolHandler.handleMessage(event);
    }
  } catch (error) {
    failConnection(error);
  }
}

function handleClose() {
  stopProtocolTimers();
  disconnectSignal.resolve();
}

let listener = null;

try {
  if (initiatorRole === "client") {
    writeJson(args.ready, {
      status: "ready",
      scenario_id: scenarioId,
      initiator_role: initiatorRole,
    });
    const serverUrl = await waitForServerUrl(
      args.registry,
      args["server-name"],
      timeoutMs,
    );

    await transportManager.connect(
      serverUrl,
      () => {
        protocolHandler.sendClientHello();
      },
      handleMessage,
      (error) => {
        failConnection(error?.message ?? "WebSocket error");
      },
      handleClose,
    );
  } else {
    const port = Number(args.port ?? "8928");
    const wsPath = args.path ?? "/sendspin";
    listener = new WebSocketServer({
      host: "127.0.0.1",
      port,
      path: wsPath,
    });

    await new Promise((resolve, reject) => {
      listener.once("listening", resolve);
      listener.once("error", reject);
    });

    registerEndpoint(
      args.registry,
      args["client-name"],
      `ws://127.0.0.1:${port}${wsPath}`,
    );
    writeJson(args.ready, {
      status: "ready",
      scenario_id: scenarioId,
      initiator_role: initiatorRole,
      url: `ws://127.0.0.1:${port}${wsPath}`,
    });

    let attached = false;
    listener.on("error", (error) => {
      failConnection(error);
    });
    listener.on("connection", (socket) => {
      if (attached) {
        socket.close();
        return;
      }
      attached = true;
      transportManager
        .attach(
          socket,
          () => {
            protocolHandler.sendClientHello();
          },
          handleMessage,
          (error) => {
            failConnection(error?.message ?? "WebSocket error");
          },
          handleClose,
        )
        .catch((error) => {
          failConnection(error);
        });
    });
  }

  await Promise.race([
    disconnectSignal.promise,
    new Promise((_, reject) =>
      setTimeout(
        () => reject(new Error("Timed out waiting for server disconnect")),
        timeoutMs,
      ),
    ),
  ]);
} catch (error) {
  failureReason = error instanceof Error ? error.message : String(error);
} finally {
  stopProtocolTimers();
  audioProcessor.close();
  if (listener) {
    await new Promise((resolve) => listener.close(resolve));
  }
}

if (failureReason === null && peerHello === null) {
  failureReason = "Connection closed before handshake completed";
}

const summary =
  failureReason === null
    ? {
        status: "ok",
        implementation: "sendspin-js",
        role: "client",
        scenario_id: scenarioId,
        initiator_role: initiatorRole,
        preferred_codec: args["preferred-codec"],
        client_name: args["client-name"],
        client_id: args["client-id"],
        peer_hello: peerHello,
        server: peerHello?.payload ?? null,
        ...(isPlayerScenario(scenarioId)
          ? {
              stream: currentStream,
              audio: {
                audio_chunk_count: chunkCount,
                received_encoded_sha256:
                  chunkCount > 0 ? hexSha256(Buffer.concat(encodedBuffers)) : null,
                received_pcm_sha256:
                  receivedHasher.sampleCount > 0 ? receivedHasher.hexdigest() : null,
                received_sample_count: receivedHasher.sampleCount,
              },
            }
          : {}),
        ...(isMetadataScenario(scenarioId)
          ? {
              metadata: {
                update_count: metadataState.updateCount,
                received: metadataState.received,
              },
            }
          : {}),
        ...(isControllerScenario(scenarioId)
          ? {
              controller: {
                received_state: controllerState.receivedState,
                sent_command: controllerState.sentCommand,
              },
            }
          : {}),
        ...(isArtworkScenario(scenarioId)
          ? {
              stream: artworkState.stream,
              artwork: {
                channel: artworkState.channel,
                received_count: artworkState.receivedCount,
                received_sha256: artworkState.receivedSha256,
                byte_count: artworkState.byteCount,
              },
            }
          : {}),
      }
    : {
        status: "error",
        implementation: "sendspin-js",
        role: "client",
        reason: failureReason,
        scenario_id: scenarioId,
        initiator_role: initiatorRole,
        preferred_codec: args["preferred-codec"],
        client_name: args["client-name"],
        client_id: args["client-id"],
        peer_hello: peerHello,
        server: peerHello?.payload ?? null,
      };

writeJson(args.summary, summary);
process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
process.exit(failureReason === null ? 0 : 1);
