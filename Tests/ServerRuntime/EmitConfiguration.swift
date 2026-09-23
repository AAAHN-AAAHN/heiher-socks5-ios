import Foundation

@main struct EmitConfiguration {
    static func main() throws {
        let folder = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try ServerSettings().configuration().write(to: folder.appendingPathComponent("defaults.yml"), atomically: true, encoding: .utf8)
        var server = ServerSettings()
        server.workers = "2"
        server.listenAddress = "127.0.0.1"
        server.listenPort = "23456"
        server.udpListenAddress = "127.0.0.1"
        server.udpListenPort = "0"
        server.listenIPv6Only = true
        server.bindInterface = "test'if"
        server.authUsername = "user'# []{}:"
        server.authPassword = "safe'@&*:"
        try server.configuration().write(to: folder.appendingPathComponent("quoted.yml"), atomically: true, encoding: .utf8)
    }
}
