import Foundation

struct PeriodicUDPEchoSettings: Codable, Sendable, Equatable {
    var enabled = false
    var destinations = "1.1.1.1"
    var period = "1000"

    static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.enabled == rhs.enabled &&
            lhs.destinations.utf8.elementsEqual(rhs.destinations.utf8) &&
            lhs.period.utf8.elementsEqual(rhs.period.utf8)
    }
}

/// Standalone Background persistence. Integrated injects its SettingsStore instead.
/// Only one I/O job and the latest pending save are retained.
final class PeriodicUDPEchoStore: @unchecked Sendable {
    typealias Load = @Sendable (Result<PeriodicUDPEchoSettings?, Error>) -> Void
    typealias Save = @Sendable (Result<Void, Error>) -> Void

    private let url: URL?
    private let queue: DispatchQueue
    private let lock = NSLock()
    private var loading: Load?
    private var pending: (PeriodicUDPEchoSettings, Save)?
    private var working = false

    init(url: URL? = nil, queue: DispatchQueue = DispatchQueue(label: "background.udp-echo.storage", qos: .utility)) {
        self.url = url
        self.queue = queue
    }

    func load(_ completion: @escaping Load) {
        enqueue { loading = completion }
    }

    func save(_ value: PeriodicUDPEchoSettings, completion: @escaping Save) {
        enqueue { pending = (value, completion) }
    }

    private func enqueue(_ update: () -> Void) {
        lock.lock()
        update()
        let start = !working
        working = true
        lock.unlock()
        if start { queue.async { self.drain() } }
    }

    private func fileURL() throws -> URL {
        if let url { return url }
        return try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                           appropriateFor: nil, create: true)
            .appendingPathComponent("periodic-udp-echo.json")
    }

    private func drain() {
        while true {
            lock.lock()
            let load = loading
            loading = nil
            let save = load == nil ? pending : nil
            if save != nil { pending = nil }
            if load == nil && save == nil { working = false }
            lock.unlock()
            if let load {
                load(Result {
                    let data: Data
                    do {
                        data = try Data(contentsOf: fileURL(), options: .mappedIfSafe)
                    } catch let error as CocoaError where error.code == .fileReadNoSuchFile {
                        return nil
                    }
                    return try JSONDecoder().decode(PeriodicUDPEchoSettings.self, from: data)
                })
            } else if let (value, completion) = save {
                completion(Result {
                    let destination = try fileURL()
                    try FileManager.default.createDirectory(at: destination.deletingLastPathComponent(),
                                                            withIntermediateDirectories: true)
                    try JSONEncoder().encode(value).write(to: destination, options: .atomic)
                })
            } else {
                return
            }
        }
    }
}
