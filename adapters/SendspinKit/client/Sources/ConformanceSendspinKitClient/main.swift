import CryptoKit
import Foundation
import Network
import SendspinKit

struct CliOptions: Sendable {
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
    let port: Int
    let path: String
    let controllerCommand: String
    let artworkFormat: String
    let artworkWidth: Int
    let artworkHeight: Int

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
            port: Int(values["port"] ?? "8928") ?? 8928,
            path: values["path"] ?? "/sendspin",
            controllerCommand: values["controller-command"] ?? "next",
            artworkFormat: values["artwork-format"] ?? "jpeg",
            artworkWidth: Int(values["artwork-width"] ?? "256") ?? 256,
            artworkHeight: Int(values["artwork-height"] ?? "256") ?? 256
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

struct ArtworkChannelInfo: Sendable {
    let source: String?
    let format: String?
    let width: Int?
    let height: Int?
}

struct ArtworkStreamInfo: Sendable {
    let channels: [ArtworkChannelInfo]
}

struct ServerInfoSnapshot: Sendable {
    let serverId: String?
    let name: String?
    let version: Int?
    let activeRoles: [String]
    let connectionReason: String?
}

struct MetadataProgressSnapshot: Sendable {
    let trackProgress: Int?
    let trackDuration: Int?
    let playbackSpeed: Int?
}

struct MetadataSnapshot: Sendable {
    let title: String?
    let artist: String?
    let albumArtist: String?
    let album: String?
    let artworkURL: String?
    let year: Int?
    let track: Int?
    let repeatMode: String?
    let shuffle: Bool?
    let progress: MetadataProgressSnapshot?
}

struct ControllerStateSnapshot: Sendable {
    let supportedCommands: [String]
    let volume: Int?
    let muted: Bool?
}

struct ControllerCommandSnapshot: Sendable {
    let command: String
    let volume: Int?
    let mute: Bool?
}

struct SummarySnapshot: Sendable {
    let peerHelloText: String?
    let server: ServerInfoSnapshot?
    let audioStream: StreamInfo?
    let artworkStream: ArtworkStreamInfo?
    let sawStreamEnd: Bool
    let terminalError: String?
    let audioChunkCount: Int
    let receivedEncodedSha256: String
    let receivedPcmSha256: String?
    let receivedSampleCount: Int
    let metadataUpdateCount: Int
    let metadata: MetadataSnapshot?
    let controllerReceivedState: ControllerStateSnapshot?
    let controllerSentCommand: ControllerCommandSnapshot?
    let artworkChannel: Int?
    let artworkCount: Int
    let artworkSha256: String?
    let artworkByteCount: Int
}

struct ConformanceAudioFormat: Codable, Sendable {
    let codec: String
    let channels: Int
    let sampleRate: Int
    let bitDepth: Int

    enum CodingKeys: String, CodingKey {
        case codec
        case channels
        case sampleRate = "sample_rate"
        case bitDepth = "bit_depth"
    }
}

struct ConformancePlayerSupport: Codable, Sendable {
    let supportedFormats: [ConformanceAudioFormat]
    let bufferCapacity: Int
    let supportedCommands: [String]

    enum CodingKeys: String, CodingKey {
        case supportedFormats = "supported_formats"
        case bufferCapacity = "buffer_capacity"
        case supportedCommands = "supported_commands"
    }
}

struct ConformanceMetadataSupport: Codable, Sendable {
    let supportedPictureFormats: [String]

    enum CodingKeys: String, CodingKey {
        case supportedPictureFormats = "supported_picture_formats"
    }
}

struct ConformanceArtworkChannel: Codable, Sendable {
    let source: String
    let format: String
    let mediaWidth: Int
    let mediaHeight: Int

    enum CodingKeys: String, CodingKey {
        case source
        case format
        case mediaWidth = "media_width"
        case mediaHeight = "media_height"
    }
}

struct ConformanceArtworkSupport: Codable, Sendable {
    let channels: [ConformanceArtworkChannel]
}

struct ConformanceClientHelloPayload: Codable, Sendable {
    let clientId: String
    let name: String
    let deviceInfo: DeviceInfo?
    let version: Int
    let supportedRoles: [String]
    let playerV1Support: ConformancePlayerSupport?
    let metadataV1Support: ConformanceMetadataSupport?
    let artworkV1Support: ConformanceArtworkSupport?

    enum CodingKeys: String, CodingKey {
        case clientId = "client_id"
        case name
        case deviceInfo = "device_info"
        case version
        case supportedRoles = "supported_roles"
        case playerV1Support = "player@v1_support"
        case metadataV1Support = "metadata@v1_support"
        case artworkV1Support = "artwork@v1_support"
    }
}

struct ConformanceClientHelloMessage: SendspinMessage {
    let type = "client/hello"
    let payload: ConformanceClientHelloPayload
}

struct ConformanceControllerCommandPayload: Codable, Sendable {
    let command: String
    let volume: Int?
    let mute: Bool?
}

struct ConformanceClientCommandPayload: Codable, Sendable {
    let controller: ConformanceControllerCommandPayload?
}

struct ConformanceClientCommandMessage: SendspinMessage {
    let type = "client/command"
    let payload: ConformanceClientCommandPayload
}

actor SummaryState {
    private var peerHelloText: String?
    private var server: ServerInfoSnapshot?
    private var audioStream: StreamInfo?
    private var artworkStream: ArtworkStreamInfo?
    private var encodedChunks: [Data] = []
    private var canonicalFloatData = Data()
    private var audioChunkCount = 0
    private var sampleCount = 0
    private var metadataUpdateCount = 0
    private var metadata: MetadataSnapshot?
    private var controllerReceivedState: ControllerStateSnapshot?
    private var controllerSentCommand: ControllerCommandSnapshot?
    private var artworkBytes = Data()
    private var artworkChannel: Int?
    private var artworkCount = 0
    private var artworkByteCount = 0
    private var textLoopCompleted = false
    private var sawStreamEnd = false
    private var terminalError: String?

    func setPeerHello(rawText: String, server: ServerInfoSnapshot?) {
        peerHelloText = rawText
        self.server = server
    }

    func setAudioStream(_ stream: StreamInfo) {
        audioStream = stream
    }

    func currentAudioStream() -> StreamInfo? {
        audioStream
    }

    func setArtworkStream(_ stream: ArtworkStreamInfo) {
        artworkStream = stream
    }

    func recordMetadata(_ metadata: MetadataSnapshot) {
        self.metadata = metadata
        metadataUpdateCount += 1
    }

    func recordControllerState(_ state: ControllerStateSnapshot, desiredCommand: String) -> Bool {
        controllerReceivedState = state
        if controllerSentCommand == nil, state.supportedCommands.contains(desiredCommand) {
            controllerSentCommand = ControllerCommandSnapshot(command: desiredCommand, volume: nil, mute: nil)
            return true
        }
        return false
    }

    func recordArtwork(channel: Int, data: Data) {
        artworkChannel = channel
        artworkCount += 1
        artworkByteCount += data.count
        artworkBytes.append(data)
    }

    func markTextLoopCompleted() {
        textLoopCompleted = true
    }

    func isTextLoopCompleted() -> Bool {
        textLoopCompleted
    }

    func markStreamEnded() {
        sawStreamEnd = true
    }

    func setTerminalError(_ message: String) {
        terminalError = message
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

    func snapshot() -> SummarySnapshot {
        let encoded = encodedChunks.reduce(into: Data()) { partial, chunk in
            partial.append(chunk)
        }
        return SummarySnapshot(
            peerHelloText: peerHelloText,
            server: server,
            audioStream: audioStream,
            artworkStream: artworkStream,
            sawStreamEnd: sawStreamEnd,
            terminalError: terminalError,
            audioChunkCount: audioChunkCount,
            receivedEncodedSha256: sha256Hex(encoded),
            receivedPcmSha256: canonicalFloatData.isEmpty ? nil : sha256Hex(canonicalFloatData),
            receivedSampleCount: sampleCount,
            metadataUpdateCount: metadataUpdateCount,
            metadata: metadata,
            controllerReceivedState: controllerReceivedState,
            controllerSentCommand: controllerSentCommand,
            artworkChannel: artworkChannel,
            artworkCount: artworkCount,
            artworkSha256: artworkBytes.isEmpty ? nil : sha256Hex(artworkBytes),
            artworkByteCount: artworkByteCount
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

func debugLog(_ message: String) {
    FileHandle.standardError.write(Data(("[SendspinKit adapter] \(message)\n").utf8))
}

func waitForServerURL(registryURL: URL, serverName: String, timeoutSeconds: Double) async throws -> String {
    let deadline = Date().addingTimeInterval(timeoutSeconds)
    while Date() < deadline {
        if let data = try? Data(contentsOf: registryURL),
           let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let entry = payload[serverName] as? [String: Any],
           let url = entry["url"] as? String,
           !url.isEmpty
        {
            return url
        }
        try await Task.sleep(for: .milliseconds(100))
    }
    throw AdapterError("Timed out waiting for server \(serverName)")
}

func registerEndpoint(registryURL: URL, clientName: String, url: String) throws {
    var payload: [String: Any] = [:]
    if let data = try? Data(contentsOf: registryURL),
       let decoded = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
    {
        payload = decoded
    }
    payload[clientName] = ["url": url]
    try writeJSON(to: registryURL, payload: payload)
}

func readyPayload(options: CliOptions, url: String? = nil) -> [String: Any] {
    var payload: [String: Any] = [
        "status": "ready",
        "scenario_id": options.scenarioId,
        "initiator_role": options.initiatorRole,
    ]
    if let url {
        payload["url"] = url
    }
    return payload
}

actor InboundWebSocketTransport {
    nonisolated let textMessages: AsyncStream<String>
    nonisolated let binaryMessages: AsyncStream<Data>

    private let connection: NWConnection
    private let queue: DispatchQueue
    private let textContinuation: AsyncStream<String>.Continuation
    private let binaryContinuation: AsyncStream<Data>.Continuation
    private var connectError: Error?
    private var isReady = false
    private var isClosed = false

    init(connection: NWConnection) {
        let (textStream, textContinuation) = AsyncStream<String>.makeStream()
        let (binaryStream, binaryContinuation) = AsyncStream<Data>.makeStream()
        self.connection = connection
        self.queue = DispatchQueue(label: "conformance.sendspinkit.inbound.transport")
        self.textMessages = textStream
        self.binaryMessages = binaryStream
        self.textContinuation = textContinuation
        self.binaryContinuation = binaryContinuation

        connection.stateUpdateHandler = { [weak self] state in
            Task { await self?.handleStateUpdate(state) }
        }
        connection.start(queue: queue)
    }

    func connect() async throws {
        let deadline = Date().addingTimeInterval(5)
        while Date() < deadline {
            if isReady {
                return
            }
            if let connectError {
                throw connectError
            }
            if isClosed {
                throw AdapterError("Inbound WebSocket connection closed before it became ready")
            }
            try await Task.sleep(for: .milliseconds(50))
        }
        throw AdapterError("Timed out waiting for inbound WebSocket to become ready")
    }

    func sendText(_ text: String) async throws {
        guard let data = text.data(using: .utf8) else {
            throw AdapterError("Failed to encode text WebSocket frame")
        }
        try await send(data: data, opcode: .text)
    }

    func disconnect() async {
        finish()
        connection.cancel()
    }

    private func send(data: Data, opcode: NWProtocolWebSocket.Opcode) async throws {
        guard !isClosed else {
            throw AdapterError("Inbound WebSocket connection is closed")
        }
        let metadata = NWProtocolWebSocket.Metadata(opcode: opcode)
        let context = NWConnection.ContentContext(identifier: "sendspin-frame", metadata: [metadata])
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            connection.send(content: data, contentContext: context, isComplete: true, completion: .contentProcessed { error in
                if let error {
                    continuation.resume(throwing: error)
                    return
                }
                continuation.resume()
            })
        }
    }

    private func handleStateUpdate(_ state: NWConnection.State) {
        switch state {
        case .ready:
            isReady = true
            receiveNextMessage()
        case let .failed(error):
            connectError = error
            finish()
        case .cancelled:
            finish()
        default:
            break
        }
    }

    private func receiveNextMessage() {
        guard !isClosed else {
            return
        }
        connection.receiveMessage { [weak self] content, context, _, error in
            Task {
                await self?.handleIncomingMessage(content: content, context: context, error: error)
            }
        }
    }

    private func handleIncomingMessage(content: Data?, context: NWConnection.ContentContext?, error: NWError?) {
        if let error {
            connectError = error
            finish()
            return
        }
        guard !isClosed else {
            return
        }

        if let metadata = context?.protocolMetadata(definition: NWProtocolWebSocket.definition) as? NWProtocolWebSocket.Metadata {
            switch metadata.opcode {
            case .text:
                if let content, let text = String(data: content, encoding: .utf8) {
                    textContinuation.yield(text)
                }
            case .binary:
                if let content {
                    binaryContinuation.yield(content)
                }
            case .close:
                finish()
                return
            default:
                break
            }
        } else if let content {
            binaryContinuation.yield(content)
        } else {
            finish()
            return
        }

        receiveNextMessage()
    }

    private func finish() {
        guard !isClosed else {
            return
        }
        isClosed = true
        textContinuation.finish()
        binaryContinuation.finish()
    }
}

actor InboundWebSocketListener {
    private let listener: NWListener
    private var acceptedConnection: NWConnection?
    private var terminalError: Error?

    init(port: Int) throws {
        let websocketOptions = NWProtocolWebSocket.Options()
        let tcpOptions = NWProtocolTCP.Options()
        let parameters = NWParameters(tls: nil, tcp: tcpOptions)
        parameters.allowLocalEndpointReuse = true
        parameters.defaultProtocolStack.applicationProtocols.insert(websocketOptions, at: 0)

        guard let endpointPort = NWEndpoint.Port(rawValue: UInt16(port)) else {
            throw AdapterError("Invalid listener port: \(port)")
        }
        listener = try NWListener(using: parameters, on: endpointPort)
        listener.newConnectionHandler = { [weak self] connection in
            Task { await self?.handleNewConnection(connection) }
        }
        listener.stateUpdateHandler = { [weak self] state in
            Task { await self?.handleStateUpdate(state) }
        }
        listener.start(queue: DispatchQueue(label: "conformance.sendspinkit.inbound.listener"))
    }

    func accept(timeoutSeconds: Double) async throws -> InboundWebSocketTransport {
        let deadline = Date().addingTimeInterval(timeoutSeconds)
        while Date() < deadline {
            if let acceptedConnection {
                self.acceptedConnection = nil
                return InboundWebSocketTransport(connection: acceptedConnection)
            }
            if let terminalError {
                throw terminalError
            }
            try await Task.sleep(for: .milliseconds(50))
        }
        throw AdapterError("Timed out waiting for inbound Sendspin server connection")
    }

    func stop() {
        listener.cancel()
    }

    private func handleNewConnection(_ connection: NWConnection) {
        if acceptedConnection == nil {
            acceptedConnection = connection
            return
        }
        connection.cancel()
    }

    private func handleStateUpdate(_ state: NWListener.State) {
        if case let .failed(error) = state {
            terminalError = error
            return
        }
        if case .cancelled = state {
            terminalError = AdapterError("Inbound WebSocket listener was cancelled")
        }
    }
}

enum AdapterTransport: Sendable {
    case outbound(WebSocketTransport)
    case inbound(InboundWebSocketTransport)

    var textMessages: AsyncStream<String> {
        switch self {
        case let .outbound(transport):
            transport.textMessages
        case let .inbound(transport):
            transport.textMessages
        }
    }

    var binaryMessages: AsyncStream<Data> {
        switch self {
        case let .outbound(transport):
            transport.binaryMessages
        case let .inbound(transport):
            transport.binaryMessages
        }
    }

    func connect() async throws {
        switch self {
        case let .outbound(transport):
            try await transport.connect()
        case let .inbound(transport):
            try await transport.connect()
        }
    }

    func disconnect() async {
        switch self {
        case let .outbound(transport):
            await transport.disconnect()
        case let .inbound(transport):
            await transport.disconnect()
        }
    }

    func send<T: SendspinMessage>(_ message: T) async throws {
        switch self {
        case let .outbound(transport):
            try await transport.send(message)
        case let .inbound(transport):
            let encoder = JSONEncoder()
            encoder.keyEncodingStrategy = .convertToSnakeCase
            let data = try encoder.encode(message)
            guard let text = String(data: data, encoding: .utf8) else {
                throw AdapterError("Failed to encode Sendspin message to UTF-8")
            }
            try await transport.sendText(text)
        }
    }
}

func isPlayerScenario(_ scenarioId: String) -> Bool {
    scenarioId == "client-initiated-pcm"
        || scenarioId == "server-initiated-pcm"
        || scenarioId == "server-initiated-flac"
}

func isMetadataScenario(_ scenarioId: String) -> Bool {
    scenarioId == "client-initiated-metadata" || scenarioId == "server-initiated-metadata"
}

func isControllerScenario(_ scenarioId: String) -> Bool {
    scenarioId == "client-initiated-controller" || scenarioId == "server-initiated-controller"
}

func isArtworkScenario(_ scenarioId: String) -> Bool {
    scenarioId == "client-initiated-artwork" || scenarioId == "server-initiated-artwork"
}

func supportedRoles(for options: CliOptions) -> [String] {
    if isMetadataScenario(options.scenarioId) {
        return ["metadata@v1"]
    }
    if isControllerScenario(options.scenarioId) {
        return ["controller@v1"]
    }
    if isArtworkScenario(options.scenarioId) {
        return ["artwork@v1"]
    }
    return ["player@v1"]
}

func supportedFormats(preferredCodec: String) -> [ConformanceAudioFormat] {
    if preferredCodec == "pcm" {
        return [
            ConformanceAudioFormat(codec: "pcm", channels: 1, sampleRate: 8000, bitDepth: 16),
        ]
    }

    return [
        ConformanceAudioFormat(codec: "flac", channels: 1, sampleRate: 8000, bitDepth: 16),
        ConformanceAudioFormat(codec: "pcm", channels: 1, sampleRate: 8000, bitDepth: 16),
    ]
}

func clientHello(options: CliOptions) -> ConformanceClientHelloMessage {
    let roles = supportedRoles(for: options)
    let includePlayer = roles.contains("player@v1")
    let includeMetadata = roles.contains("metadata@v1")
    let includeArtwork = roles.contains("artwork@v1")

    return ConformanceClientHelloMessage(
        payload: ConformanceClientHelloPayload(
            clientId: options.clientId,
            name: options.clientName,
            deviceInfo: DeviceInfo.current,
            version: 1,
            supportedRoles: roles,
            playerV1Support: includePlayer
                ? ConformancePlayerSupport(
                    supportedFormats: supportedFormats(preferredCodec: options.preferredCodec),
                    bufferCapacity: 2_000_000,
                    supportedCommands: ["volume", "mute"]
                )
                : nil,
            metadataV1Support: includeMetadata
                ? ConformanceMetadataSupport(supportedPictureFormats: [])
                : nil,
            artworkV1Support: includeArtwork
                ? ConformanceArtworkSupport(
                    channels: [
                        ConformanceArtworkChannel(
                            source: "album",
                            format: options.artworkFormat.lowercased(),
                            mediaWidth: options.artworkWidth,
                            mediaHeight: options.artworkHeight
                        ),
                    ]
                )
                : nil
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
    ClientTimeMessage(
        payload: ClientTimePayload(clientTransmitted: Int64(Date().timeIntervalSince1970 * 1_000_000))
    )
}

func clientCommand(_ command: String) -> ConformanceClientCommandMessage {
    ConformanceClientCommandMessage(
        payload: ConformanceClientCommandPayload(
            controller: ConformanceControllerCommandPayload(command: command, volume: nil, mute: nil)
        )
    )
}

func stringValue(_ value: Any?) -> String? {
    if let string = value as? String {
        return string
    }
    if let number = value as? NSNumber {
        return number.stringValue
    }
    return nil
}

func intValue(_ value: Any?) -> Int? {
    if let int = value as? Int {
        return int
    }
    if let number = value as? NSNumber {
        return number.intValue
    }
    if let string = value as? String {
        return Int(string)
    }
    return nil
}

func boolValue(_ value: Any?) -> Bool? {
    if let bool = value as? Bool {
        return bool
    }
    if let number = value as? NSNumber {
        return number.boolValue
    }
    if let string = value as? String {
        switch string.lowercased() {
        case "1", "true", "yes", "on":
            return true
        case "0", "false", "no", "off":
            return false
        default:
            return nil
        }
    }
    return nil
}

func dictionaryValue(_ value: Any?) -> [String: Any]? {
    value as? [String: Any]
}

func arrayValue(_ value: Any?) -> [Any]? {
    value as? [Any]
}

func normalizeMetadata(_ metadata: [String: Any]) -> MetadataSnapshot {
    let progress = dictionaryValue(metadata["progress"]).map {
        MetadataProgressSnapshot(
            trackProgress: intValue($0["track_progress"]),
            trackDuration: intValue($0["track_duration"]),
            playbackSpeed: intValue($0["playback_speed"])
        )
    }
    return MetadataSnapshot(
        title: stringValue(metadata["title"]),
        artist: stringValue(metadata["artist"]),
        albumArtist: stringValue(metadata["album_artist"]),
        album: stringValue(metadata["album"]),
        artworkURL: stringValue(metadata["artwork_url"]),
        year: intValue(metadata["year"]),
        track: intValue(metadata["track"]),
        repeatMode: stringValue(metadata["repeat"]),
        shuffle: boolValue(metadata["shuffle"]),
        progress: progress
    )
}

func normalizeController(_ controller: [String: Any]) -> ControllerStateSnapshot {
    let supported = (arrayValue(controller["supported_commands"]) ?? []).compactMap { stringValue($0) }
    return ControllerStateSnapshot(
        supportedCommands: supported,
        volume: intValue(controller["volume"]),
        muted: boolValue(controller["muted"])
    )
}

func parseServerInfo(payload: [String: Any]) -> ServerInfoSnapshot {
    ServerInfoSnapshot(
        serverId: stringValue(payload["server_id"]),
        name: stringValue(payload["name"]),
        version: intValue(payload["version"]),
        activeRoles: (arrayValue(payload["active_roles"]) ?? []).compactMap { stringValue($0) },
        connectionReason: stringValue(payload["connection_reason"])
    )
}

func parseAudioStream(payload: [String: Any]) -> StreamInfo? {
    guard let codec = stringValue(payload["codec"]),
          let sampleRate = intValue(payload["sample_rate"]),
          let channels = intValue(payload["channels"]),
          let bitDepth = intValue(payload["bit_depth"])
    else {
        return nil
    }
    return StreamInfo(
        codec: codec,
        sampleRate: sampleRate,
        channels: channels,
        bitDepth: bitDepth,
        codecHeader: stringValue(payload["codec_header"])
    )
}

func parseArtworkStream(payload: [String: Any]) -> ArtworkStreamInfo {
    let channels = (arrayValue(payload["channels"]) ?? []).compactMap { raw -> ArtworkChannelInfo? in
        guard let channel = raw as? [String: Any] else {
            return nil
        }
        return ArtworkChannelInfo(
            source: stringValue(channel["source"]),
            format: stringValue(channel["format"]),
            width: intValue(channel["width"]),
            height: intValue(channel["height"])
        )
    }
    return ArtworkStreamInfo(channels: channels)
}

func serverDictionary(_ payload: ServerInfoSnapshot?) -> Any? {
    guard let payload else {
        return nil
    }
    return [
        "server_id": payload.serverId as Any,
        "name": payload.name as Any,
        "version": payload.version as Any,
        "active_roles": payload.activeRoles,
        "connection_reason": payload.connectionReason as Any,
    ]
}

func audioStreamDictionary(_ stream: StreamInfo?) -> Any? {
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

func artworkStreamDictionary(_ stream: ArtworkStreamInfo?) -> Any? {
    guard let stream else {
        return nil
    }
    return [
        "channels": stream.channels.map { channel in
            [
                "source": channel.source as Any,
                "format": channel.format as Any,
                "width": channel.width as Any,
                "height": channel.height as Any,
            ]
        },
    ]
}

func metadataDictionary(_ metadata: MetadataSnapshot?) -> Any? {
    guard let metadata else {
        return nil
    }
    return [
        "title": metadata.title as Any,
        "artist": metadata.artist as Any,
        "album_artist": metadata.albumArtist as Any,
        "album": metadata.album as Any,
        "artwork_url": metadata.artworkURL as Any,
        "year": metadata.year as Any,
        "track": metadata.track as Any,
        "repeat": metadata.repeatMode as Any,
        "shuffle": metadata.shuffle as Any,
        "progress": metadata.progress.map { progress in
            [
                "track_progress": progress.trackProgress as Any,
                "track_duration": progress.trackDuration as Any,
                "playback_speed": progress.playbackSpeed as Any,
            ]
        } as Any,
    ]
}

func controllerDictionary(_ controller: ControllerStateSnapshot?) -> Any? {
    guard let controller else {
        return nil
    }
    return [
        "supported_commands": controller.supportedCommands,
        "volume": controller.volume as Any,
        "muted": controller.muted as Any,
    ]
}

func commandDictionary(_ command: ControllerCommandSnapshot?) -> Any? {
    guard let command else {
        return nil
    }
    var payload: [String: Any] = [
        "command": command.command,
    ]
    if let volume = command.volume {
        payload["volume"] = volume
    }
    if let mute = command.mute {
        payload["mute"] = mute
    }
    return payload
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

func summaryPayload(
    options: CliOptions,
    snapshot: SummarySnapshot,
    status: String,
    reason: String? = nil
) -> [String: Any] {
    var payload: [String: Any] = [
        "status": status,
        "implementation": "SendspinKit",
        "role": "client",
        "scenario_id": options.scenarioId,
        "initiator_role": options.initiatorRole,
        "preferred_codec": options.preferredCodec,
        "client_name": options.clientName,
        "client_id": options.clientId,
        "peer_hello": peerHelloObject(snapshot.peerHelloText),
        "server": serverDictionary(snapshot.server) as Any,
    ]
    if let reason {
        payload["reason"] = reason
    }

    if isPlayerScenario(options.scenarioId) {
        payload["stream"] = audioStreamDictionary(snapshot.audioStream) as Any
        payload["audio"] = [
            "audio_chunk_count": snapshot.audioChunkCount,
            "received_encoded_sha256": snapshot.audioChunkCount > 0
                ? snapshot.receivedEncodedSha256 as Any
                : NSNull(),
            "received_pcm_sha256": snapshot.receivedPcmSha256 as Any,
            "received_sample_count": snapshot.receivedSampleCount,
        ]
    } else if isMetadataScenario(options.scenarioId) {
        payload["metadata"] = [
            "update_count": snapshot.metadataUpdateCount,
            "received": metadataDictionary(snapshot.metadata) as Any,
        ]
    } else if isControllerScenario(options.scenarioId) {
        payload["controller"] = [
            "received_state": controllerDictionary(snapshot.controllerReceivedState) as Any,
            "sent_command": commandDictionary(snapshot.controllerSentCommand) as Any,
        ]
    } else if isArtworkScenario(options.scenarioId) {
        payload["stream"] = artworkStreamDictionary(snapshot.artworkStream) as Any
        payload["artwork"] = [
            "channel": snapshot.artworkChannel as Any,
            "received_count": snapshot.artworkCount,
            "received_sha256": snapshot.artworkSha256 as Any,
            "byte_count": snapshot.artworkByteCount,
        ]
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

            let transport: AdapterTransport
            var listener: InboundWebSocketListener?

            if options.initiatorRole == "client" {
                try writeJSON(to: options.ready, payload: readyPayload(options: options))
                let serverURLString = try await waitForServerURL(
                    registryURL: options.registry,
                    serverName: options.serverName,
                    timeoutSeconds: options.timeoutSeconds
                )
                guard let serverURL = URL(string: serverURLString) else {
                    throw AdapterError("Invalid server URL: \(serverURLString)")
                }
                let outboundTransport = WebSocketTransport(url: serverURL)
                transport = .outbound(outboundTransport)
                try await transport.connect()
                debugLog("Connected transport to \(serverURLString)")
            } else {
                let inboundListener = try InboundWebSocketListener(port: options.port)
                listener = inboundListener
                let listenerURL = "ws://127.0.0.1:\(options.port)\(options.path)"
                try registerEndpoint(
                    registryURL: options.registry,
                    clientName: options.clientName,
                    url: listenerURL
                )
                try writeJSON(
                    to: options.ready,
                    payload: readyPayload(options: options, url: listenerURL)
                )
                debugLog("Listening for inbound Sendspin server on \(listenerURL)")
                let inboundTransport = try await inboundListener.accept(timeoutSeconds: options.timeoutSeconds)
                transport = .inbound(inboundTransport)
                try await transport.connect()
                await inboundListener.stop()
                debugLog("Accepted inbound transport on \(listenerURL)")
            }

            try await transport.send(clientHello(options: options))
            debugLog("Sent client/hello")

            let heartbeatTask = Task {
                while !Task.isCancelled {
                    try? await transport.send(clientTime())
                    try? await Task.sleep(for: .seconds(1))
                }
            }

            let textTask = Task {
                do {
                    for await text in transport.textMessages {
                        guard let data = text.data(using: .utf8),
                              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                              let type = json["type"] as? String
                        else {
                            continue
                        }

                        let payload = dictionaryValue(json["payload"])

                        switch type {
                        case "server/hello":
                            debugLog("Received server/hello")
                            await state.setPeerHello(
                                rawText: text,
                                server: payload.map(parseServerInfo)
                            )
                            if isPlayerScenario(options.scenarioId) {
                                try await transport.send(clientState())
                                debugLog("Sent client/state")
                            }
                        case "server/state":
                            if isMetadataScenario(options.scenarioId),
                               let metadataPayload = dictionaryValue(payload?["metadata"])
                            {
                                await state.recordMetadata(normalizeMetadata(metadataPayload))
                                debugLog("Recorded metadata update")
                            }
                            if isControllerScenario(options.scenarioId),
                               let controllerPayload = dictionaryValue(payload?["controller"])
                            {
                                let shouldSend = await state.recordControllerState(
                                    normalizeController(controllerPayload),
                                    desiredCommand: options.controllerCommand
                                )
                                if shouldSend {
                                    try await transport.send(clientCommand(options.controllerCommand))
                                    debugLog("Sent client/command \(options.controllerCommand)")
                                }
                            }
                        case "stream/start":
                            if isPlayerScenario(options.scenarioId),
                               let playerPayload = dictionaryValue(payload?["player"]),
                               let stream = parseAudioStream(payload: playerPayload)
                            {
                                await state.setAudioStream(stream)
                                debugLog("Received stream/start codec=\(stream.codec)")
                            }
                            if isArtworkScenario(options.scenarioId),
                               let artworkPayload = dictionaryValue(payload?["artwork"])
                            {
                                await state.setArtworkStream(parseArtworkStream(payload: artworkPayload))
                                debugLog("Received artwork stream/start")
                            }
                        case "stream/metadata":
                            if isMetadataScenario(options.scenarioId), let payload {
                                await state.recordMetadata(normalizeMetadata(payload))
                                debugLog("Recorded stream/metadata update")
                            }
                        case "session/update":
                            if isMetadataScenario(options.scenarioId),
                               let metadataPayload = dictionaryValue(payload?["metadata"])
                            {
                                await state.recordMetadata(normalizeMetadata(metadataPayload))
                                debugLog("Recorded session/update metadata")
                            }
                        case "stream/end":
                            await state.markStreamEnded()
                            debugLog("Received stream/end")
                        default:
                            break
                        }
                    }
                    await state.markTextLoopCompleted()
                } catch {
                    await state.setTerminalError(String(describing: error))
                    await state.markTextLoopCompleted()
                }
            }

            let binaryTask = Task {
                do {
                    for await data in transport.binaryMessages {
                        guard let message = BinaryMessage(data: data) else {
                            continue
                        }

                        if isArtworkScenario(options.scenarioId) {
                            switch message.type {
                            case .artworkChannel0:
                                await state.recordArtwork(channel: 0, data: message.data)
                            case .artworkChannel1:
                                await state.recordArtwork(channel: 1, data: message.data)
                            case .artworkChannel2:
                                await state.recordArtwork(channel: 2, data: message.data)
                            case .artworkChannel3:
                                await state.recordArtwork(channel: 3, data: message.data)
                            default:
                                break
                            }
                            if message.type != .audioChunk {
                                continue
                            }
                        }

                        guard isPlayerScenario(options.scenarioId), message.type == .audioChunk else {
                            continue
                        }
                        guard let stream = await state.currentAudioStream() else {
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
                } catch {
                    await state.setTerminalError(String(describing: error))
                }
            }

            let deadline = Date().addingTimeInterval(options.timeoutSeconds)
            while Date() < deadline {
                if await state.isTextLoopCompleted() {
                    break
                }
                try await Task.sleep(for: .milliseconds(100))
            }
            guard await state.isTextLoopCompleted() else {
                throw AdapterError("Timed out waiting for server disconnect")
            }

            heartbeatTask.cancel()
            _ = await textTask.result
            debugLog("Message loop completed; allowing binary grace period")
            try? await Task.sleep(for: .milliseconds(500))
            binaryTask.cancel()
            _ = await binaryTask.result
            await transport.disconnect()

            let snapshot = await state.snapshot()
            if let terminalError = snapshot.terminalError {
                throw AdapterError(terminalError)
            }
            guard snapshot.peerHelloText != nil else {
                throw AdapterError("Connection closed before handshake completed")
            }
            if isPlayerScenario(options.scenarioId), !snapshot.sawStreamEnd {
                throw AdapterError("Connection closed before stream/end was received")
            }

            let payload = summaryPayload(options: options, snapshot: snapshot, status: "ok")
            try writeJSON(to: options.summary, payload: payload)
            debugLog("Wrote success summary")
            let output = try JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys])
            FileHandle.standardOutput.write(output)
            FileHandle.standardOutput.write(Data([0x0A]))
            Foundation.exit(0)
        } catch {
            let reason = String(describing: error)
            if let options = parsedOptions {
                let snapshot = await state.snapshot()
                let payload = summaryPayload(options: options, snapshot: snapshot, status: "error", reason: reason)
                try? writeJSON(to: options.summary, payload: payload)
                debugLog("Wrote error summary: \(reason)")
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
