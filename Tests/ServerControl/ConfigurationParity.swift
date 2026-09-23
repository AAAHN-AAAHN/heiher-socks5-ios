import Foundation

@main struct ConfigurationParity {
    static func main() throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let oldDefaults = try encoder.encode(OriginalServerSettings())
        let newDefaults = try encoder.encode(ServerSettings())
        precondition(oldDefaults == newDefaults, "Original defaults/schema changed")
        var matched = 0
        for index in 0..<512 {
            var current = ServerSettings()
            current.workers = ["1", "4", "64", "0", "65", "bad"][index % 6]
            current.listenPort = index % 11 == 0 ? "65536" : String(1024 + index)
            current.udpListenPort = index % 2 == 0 ? "0" : "1080"
            current.listenIPv6Only = index % 3 == 0
            current.listenAddress = index % 7 == 0 ? String(repeating: "x", count: 256) : "::"
            current.authUsername = index % 5 == 0 ? "u\nname" : "user'\(index)"
            current.authPassword = "p'\\#{}: \(index)"
            let encoded = try encoder.encode(current)
            let original = try JSONDecoder().decode(OriginalServerSettings.self, from: encoded)
            let before = Result { try original.configuration() }
            let after = Result { try current.configuration() }
            switch (before, after) {
            case (.success(let a), .success(let b)): precondition(a == b, "Generated YAML changed")
            case (.failure(let a), .failure(let b)): precondition(a.localizedDescription == b.localizedDescription, "Validation contract changed")
            default: preconditionFailure("Validation result differs")
            }
            matched += 1
        }
        print("PASS: original JSON defaults and \(matched) configuration/validation parity cases; not device tests")
    }
}
