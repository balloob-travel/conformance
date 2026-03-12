import CryptoKit
import Foundation
import SendspinKit

struct CliOptions {
    let clientName: String
    let clientId: String
    let summary: URL
    let ready: URL
    let registry: URL
    let scenarioId: String
    let initiatorRole: String
    let preferredCodec: String
    let serverName: String
    let serverId: String
    let timeoutSeconds: Double

    static func parse(_ arguments: [String]) throws -> CliOptions {
        let filteredArguments = arguments.filter { $0 != "--" }
        var values: [String: String] = [:]
        var index = 0
        while index < filteredArguments.count {
            let key = filteredArguments[index]
            guard key.hasPrefix("--"), index + 1 < filteredArguments.count else {
                throw AdapterError("Invalid arguments near \(key)")
            }
            values[String(key.dropFirst(2))] = filteredArguments[index + 1]
            index += 2
        }

        return CliOptions(
            clientName: try require(values, key: "client-name"),
            clientId: try require(values, key: "client-id"),
            summary: URL(fileURLWithPath: try require(values, key: "summary")),
            ready: URL(fileURLWithPath: try require(values, key: "ready")),
            registry: URL(fileURLWithPath: try require(values, key: "registry")),
            scenarioId: values["scenario-id"] ?? "client-initiated-pcm",
            initiatorRole: values["initiator-role"] ?? "client",
            preferredCodec: values["preferred-codec"] ?? "pcm",
            serverName: values["server-name"] ?? "Sendspin Conformance Server",
            serverId: values["server-id"] ?? "conformance-server",
            timeoutSeconds: Double(values["timeout-seconds"] ?? "30") ?? 30,
        )
    }

    private static func require(_ values: [String: String], key: String) throws -> String {
        guard let value = values[key], !value.isEmpty else {
            throw AdapterError("Missing required option --\(key)")
        }
        return value
    }
}

struct AdapterError: Error, CustomStringConvertible {
    let description: String

    init(_ description: String) {
        self.description = description
    }
}

struct StreamInfo: Sendable {
    let codec: String
    let sampleRate: Int
    let channels: Int
    let bitDepth: Int
    let codecHeader: String?
}

actor SummaryState {
    private var peerHelloText: String?
    private var serverPayload: ServerHelloPayload?
    private var stream: StreamInfo?
    private var encodedChunks: [Data] = []
    private var canonicalFloatData = Data()
    private var audioChunkCount = 0
    private var sampleCount = 0

    func setPeerHello(rawText: String, payload: ServerHelloPayload) {
        peerHelloText = rawText
        serverPayload = payload
    }

    func setStream(_ stream: StreamInfo) {
        self.stream = stream
    }

    func currentStream() -> StreamInfo? {
        stream
    }

    func appendAudio(encoded: Data, pcm: Data?, bitDepth: Int?) throws {
        encodedChunks.append(encoded)
        audioChunkCount += 1
        guard let pcm, let bitDepth else {
            return
        }
        let floatData = try canonicalFloatBytes(from: pcm, bitDepth: bitDepth)
        canonicalFloatData.append(floatData)
        sampleCount += floatData.count / 4
    }

    func snapshot() -> (
        peerHelloText: String?,
        serverPayload: ServerHelloPayload?,
        stream: StreamInfo?,
        audioChunkCount: Int,
        receivedEncodedSha256: String,
        receivedPcmSha256: String?,
        receivedSampleCount: Int
    ) {
        let encoded = encodedChunks.reduce(into: Data(), { partial, chunk in
            partial.append(chunk)
        })
        return (
            peerHelloText: peerHelloText,
            serverPayload: serverPayload,
            stream: stream,
            audioChunkCount: audioChunkCount,
            receivedEncodedSha256: sha256Hex(encoded),
            receivedPcmSha256: canonicalFloatData.isEmpty ? nil : sha256Hex(canonicalFloatData),
            receivedSampleCount: sampleCount
        )
    }
}

func sha256Hex(_ data: Data) -> String {
    SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
}

func canonicalFloatBytes(from pcmData: Data, bitDepth: Int) throws -> Data {
    var output = Data()
    switch bitDepth {
    case 16:
        guard pcmData.count.isMultiple(of: 2) else {
            throw AdapterError("Invalid PCM payload length for 16-bit audio: \(pcmData.count)")
        }
        for offset in stride(from: 0, to: pcmData.count, by: 2) {
            let sample = pcmData.subdata(in: offset ..< offset + 2).withUnsafeBytes {
                $0.load(as: Int16.self)
            }
            var value = Float(sample) / 32768.0
            output.append(Data(bytes: &value, count: MemoryLayout<Float>.size))
        }
    case 24:
        guard pcmData.count.isMultiple(of: 3) else {
            throw AdapterError("Invalid PCM payload length for 24-bit audio: \(pcmData.count)")
        }
        for offset in stride(from: 0, to: pcmData.count, by: 3) {
            let bytes = [UInt8](pcmData[offset ..< offset + 3])
            var value = Int32(bytes[0]) | (Int32(bytes[1]) << 8) | (Int32(bytes[2]) << 16)
            if value & 0x800000 != 0 {
                value |= ~0x00FF_FFFF
            }
            var sample = Float(value) / 8_388_608.0
            output.append(Data(bytes: &sample, count: MemoryLayout<Float>.size))
        }
    case 32:
        guard pcmData.count.isMultiple(of: 4) else {
            throw AdapterError("Invalid PCM payload length for 32-bit audio: \(pcmData.count)")
        }
        for offset in stride(from: 0, to: pcmData.count, by: 4) {
            let sample = pcmData.subdata(in: offset ..< offset + 4).withUnsafeBytes {
                $0.load(as: Int32.self)
            }
            var value = Float(sample) / 2_147_483_648.0
            output.append(Data(bytes: &value, count: MemoryLayout<Float>.size))
        }
    default:
        throw AdapterError("Unsupported PCM bit depth: \(bitDepth)")
    }
    return output
}

func writeJSON(to url: URL, payload: Any) throws {
    try FileManager.default.createDirectory(
        at: url.deletingLastPathComponent(),
        withIntermediateDirectories: true
    )
    var data = try JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys])
    data.append(0x0A)
    try data.write(to: url)
}

func waitForServerURL(registryURL: URL, serverName: String, timeoutSeconds: Double) async throws -> String {
    let deadline = Date().addingTimeInterval(timeoutSeconds)
    while Date() < deadline {
        if let data = try? Data(contentsOf: registryURL),
           let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let entry = payload[serverName] as? [String: Any],
           let url = entry["url"] as? String,
           !url.isEmpty {
            return url
        }
        try await Task.sleep(for: .milliseconds(100))
    }
    throw AdapterError("Timed out waiting for server \(serverName)")
}

func playerSupport() -> PlayerSupport {
    PlayerSupport(
        supportedFormats: [
            AudioFormatSpec(codec: .pcm, channels: 1, sampleRate: 8000, bitDepth: 16),
        ],
        bufferCapacity: 2_000_000,
        supportedCommands: [.volume, .mute]
    )
}

func clientHello(options: CliOptions) -> ClientHelloMessage {
    ClientHelloMessage(
        payload: ClientHelloPayload(
            clientId: options.clientId,
            name: options.clientName,
            deviceInfo: DeviceInfo.current,
            version: 1,
            supportedRoles: [.playerV1],
            playerV1Support: playerSupport(),
            metadataV1Support: nil,
            artworkV1Support: nil,
            visualizerV1Support: nil
        )
    )
}

func clientState() -> ClientStateMessage {
    ClientStateMessage(
        payload: ClientStatePayload(
            player: PlayerStateObject(state: .synchronized, volume: 100, muted: false)
        )
    )
}

func clientTime() -> ClientTimeMessage {
    ClientTimeMessage(payload: ClientTimePayload(clientTransmitted: Int64(Date().timeIntervalSince1970 * 1_000_000)))
}

func streamDictionary(_ stream: StreamInfo?) -> Any? {
    guard let stream else {
        return nil
    }
    return [
        "codec": stream.codec,
        "sample_rate": stream.sampleRate,
        "channels": stream.channels,
        "bit_depth": stream.bitDepth,
        "codec_header": stream.codecHeader as Any,
    ]
}

func serverDictionary(_ payload: ServerHelloPayload?) -> Any? {
    guard let payload else {
        return nil
    }
    return [
        "server_id": payload.serverId,
        "name": payload.name,
        "version": payload.version,
        "active_roles": payload.activeRoles.map(\.identifier),
        "connection_reason": payload.connectionReason.rawValue,
    ]
}

func peerHelloObject(_ text: String?) -> Any {
    guard let text,
          let data = text.data(using: .utf8),
          let payload = try? JSONSerialization.jsonObject(with: data)
    else {
        return NSNull()
    }
    return payload
}

@main
struct Main {
    static func main() async {
        let parsedOptions = try? CliOptions.parse(Array(CommandLine.arguments.dropFirst()))
        let state = SummaryState()
        do {
            guard let options = parsedOptions else {
                throw AdapterError("Failed to parse CLI options")
            }

            let ready: [String: Any] = [
                "status": "ready",
                "scenario_id": options.scenarioId,
                "initiator_role": options.initiatorRole,
            ]
            try writeJSON(to: options.ready, payload: ready)

            guard options.initiatorRole == "client" else {
                let payload: [String: Any] = [
                    "status": "error",
                    "reason": "SendspinKit client adapter only supports client-initiated scenarios",
                    "implementation": "SendspinKit",
                    "role": "client",
                    "scenario_id": options.scenarioId,
                    "initiator_role": options.initiatorRole,
                    "preferred_codec": options.preferredCodec,
                    "client_name": options.clientName,
                    "client_id": options.clientId,
                    "peer_hello": NSNull(),
                ]
                try writeJSON(to: options.summary, payload: payload)
                if let data = try? JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys]) {
                    FileHandle.standardOutput.write(data)
                    FileHandle.standardOutput.write(Data([0x0A]))
                }
                Foundation.exit(1)
            }

            let serverURLString = try await waitForServerURL(
                registryURL: options.registry,
                serverName: options.serverName,
                timeoutSeconds: options.timeoutSeconds
            )
            guard let serverURL = URL(string: serverURLString) else {
                throw AdapterError("Invalid server URL: \(serverURLString)")
            }

            let transport = WebSocketTransport(url: serverURL)
            let decoder = JSONDecoder()

            try await transport.connect()
            try await transport.send(clientHello(options: options))

            let heartbeatTask = Task {
                while !Task.isCancelled {
                    try? await transport.send(clientTime())
                    try? await Task.sleep(for: .seconds(1))
                }
            }

            let textTask = Task {
                for await text in transport.textMessages {
                    guard let data = text.data(using: .utf8),
                          let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                          let type = json["type"] as? String
                    else {
                        continue
                    }

                    switch type {
                    case "server/hello":
                        let message = try decoder.decode(ServerHelloMessage.self, from: data)
                        await state.setPeerHello(rawText: text, payload: message.payload)
                        try await transport.send(clientState())
                    case "stream/start":
                        let message = try decoder.decode(StreamStartMessage.self, from: data)
                        if let player = message.payload.player {
                            await state.setStream(
                                StreamInfo(
                                    codec: player.codec,
                                    sampleRate: player.sampleRate,
                                    channels: player.channels,
                                    bitDepth: player.bitDepth,
                                    codecHeader: player.codecHeader
                                )
                            )
                        }
                    case "stream/end":
                        await transport.disconnect()
                        break
                    default:
                        break
                    }
                }
            }

            let binaryTask = Task {
                for await data in transport.binaryMessages {
                    guard let message = BinaryMessage(data: data), message.type == .audioChunk else {
                        continue
                    }
                    guard let stream = await state.currentStream() else {
                        throw AdapterError("Received audio before stream/start")
                    }
                    if stream.codec == "pcm" {
                        let pcmData = try PCMDecoder(bitDepth: stream.bitDepth, channels: stream.channels)
                            .decode(message.data)
                        try await state.appendAudio(encoded: message.data, pcm: pcmData, bitDepth: stream.bitDepth)
                        continue
                    }
                    guard stream.codec == "flac" else {
                        throw AdapterError("Unsupported codec for current scenario: \(stream.codec)")
                    }
                    try await state.appendAudio(encoded: message.data, pcm: nil, bitDepth: nil)
                }
            }

            let timeoutTask = Task {
                try await Task.sleep(for: .seconds(options.timeoutSeconds))
                throw AdapterError("Timed out waiting for server disconnect")
            }

            do {
                try await textTask.value
                heartbeatTask.cancel()
                timeoutTask.cancel()
                _ = try? await binaryTask.value
            } catch {
                heartbeatTask.cancel()
                timeoutTask.cancel()
                binaryTask.cancel()
                throw error
            }

            let snapshot = await state.snapshot()
            guard let peerHelloText = snapshot.peerHelloText else {
                throw AdapterError("Connection closed before handshake completed")
            }

            let payload: [String: Any] = [
                "status": "ok",
                "implementation": "SendspinKit",
                "role": "client",
                "scenario_id": options.scenarioId,
                "initiator_role": options.initiatorRole,
                "preferred_codec": options.preferredCodec,
                "client_name": options.clientName,
                "client_id": options.clientId,
                "peer_hello": peerHelloObject(peerHelloText),
                "server": serverDictionary(snapshot.serverPayload) as Any,
                "stream": streamDictionary(snapshot.stream) as Any,
                "audio": [
                    "audio_chunk_count": snapshot.audioChunkCount,
                    "received_encoded_sha256": snapshot.receivedEncodedSha256,
                    "received_pcm_sha256": snapshot.receivedPcmSha256 as Any,
                    "received_sample_count": snapshot.receivedSampleCount,
                ],
            ]

            try writeJSON(to: options.summary, payload: payload)
            let output = try JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys])
            FileHandle.standardOutput.write(output)
            FileHandle.standardOutput.write(Data([0x0A]))
        } catch {
            let reason = String(describing: error)
            if let options = parsedOptions {
                let snapshot = await state.snapshot()
                let payload: [String: Any] = [
                    "status": "error",
                    "reason": reason,
                    "implementation": "SendspinKit",
                    "role": "client",
                    "scenario_id": options.scenarioId,
                    "initiator_role": options.initiatorRole,
                    "preferred_codec": options.preferredCodec,
                    "client_name": options.clientName,
                    "client_id": options.clientId,
                    "peer_hello": peerHelloObject(snapshot.peerHelloText),
                    "server": serverDictionary(snapshot.serverPayload) as Any,
                    "stream": streamDictionary(snapshot.stream) as Any,
                    "audio": [
                        "audio_chunk_count": snapshot.audioChunkCount,
                        "received_encoded_sha256": snapshot.audioChunkCount > 0 ? snapshot.receivedEncodedSha256 as Any : NSNull(),
                        "received_pcm_sha256": snapshot.receivedPcmSha256 as Any,
                        "received_sample_count": snapshot.receivedSampleCount,
                    ],
                ]
                try? writeJSON(to: options.summary, payload: payload)
                if let data = try? JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys]) {
                    FileHandle.standardOutput.write(data)
                    FileHandle.standardOutput.write(Data([0x0A]))
                }
            }
            fputs("\(reason)\n", stderr)
            Foundation.exit(1)
        }
    }
}
