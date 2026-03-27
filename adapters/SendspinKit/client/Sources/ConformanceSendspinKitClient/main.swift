import Foundation

struct AdapterError: Error, CustomStringConvertible {
    let description: String

    init(_ description: String) {
        self.description = description
    }
}

struct CliOptions {
    let summaryPath: String
    let readyPath: String
    let scenarioID: String?
    let initiatorRole: String?
    let preferredCodec: String?
    let clientID: String?
    let clientName: String?
    let failureReason: String

    static func parse(_ arguments: [String]) throws -> CliOptions {
        let filtered = arguments.filter { $0 != "--" }
        var values: [String: String] = [:]
        var index = 0
        while index < filtered.count {
            let key = filtered[index]
            guard key.hasPrefix("--"), index + 1 < filtered.count else {
                throw AdapterError("Invalid arguments near \(key)")
            }
            values[String(key.dropFirst(2))] = filtered[index + 1]
            index += 2
        }

        guard let summaryPath = values["summary"], !summaryPath.isEmpty else {
            throw AdapterError("Missing required option --summary")
        }
        guard let readyPath = values["ready"], !readyPath.isEmpty else {
            throw AdapterError("Missing required option --ready")
        }

        return CliOptions(
            summaryPath: summaryPath,
            readyPath: readyPath,
            scenarioID: values["scenario-id"],
            initiatorRole: values["initiator-role"],
            preferredCodec: values["preferred-codec"],
            clientID: values["client-id"],
            clientName: values["client-name"],
            failureReason: values["failure-reason"]
                ?? "SendspinKit client conformance is intentionally disabled until the adapter can use the public SDK like an example application, without bespoke protocol code."
        )
    }
}

func writeJSON(to path: String, payload: [String: Any?]) throws {
    let url = URL(fileURLWithPath: path)
    try FileManager.default.createDirectory(
        at: url.deletingLastPathComponent(),
        withIntermediateDirectories: true
    )
    let sanitized = payload.mapValues { $0 ?? NSNull() }
    let data = try JSONSerialization.data(withJSONObject: sanitized, options: [.prettyPrinted])
    try data.write(to: url)
}

@main
struct ConformanceSendspinKitClient {
    static func main() throws {
        let options = try CliOptions.parse(Array(CommandLine.arguments.dropFirst()))

        let readyPayload: [String: Any?] = [
            "status": "ready",
            "implementation": "SendspinKit",
            "scenario_id": options.scenarioID,
            "initiator_role": options.initiatorRole,
        ]
        try writeJSON(to: options.readyPath, payload: readyPayload)

        let summaryPayload: [String: Any?] = [
            "status": "error",
            "implementation": "SendspinKit",
            "role": "client",
            "reason": options.failureReason,
            "scenario_id": options.scenarioID,
            "initiator_role": options.initiatorRole,
            "preferred_codec": options.preferredCodec,
            "client_id": options.clientID,
            "client_name": options.clientName,
            "peer_hello": nil,
        ]
        try writeJSON(to: options.summaryPath, payload: summaryPayload)

        let stdoutData = try JSONSerialization.data(
            withJSONObject: summaryPayload.mapValues { $0 ?? NSNull() },
            options: [.prettyPrinted]
        )
        FileHandle.standardOutput.write(stdoutData)
        FileHandle.standardOutput.write(Data([0x0A]))
        Foundation.exit(1)
    }
}
