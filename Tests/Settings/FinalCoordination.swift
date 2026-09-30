import Foundation

// Only OS coordination/security-scope outcomes are controlled. The complete
// production store body, real files, decoder and MainActor application remain.
enum ProviderBoundary {
    struct Rule {
        var target: URL?
        var scope = true
        var beforeError = false
        var afterError = false
        var omitAccessor = false
    }
    static let condition = NSCondition()
    nonisolated(unsafe) static var rules = [String: Rule]()
    nonisolated(unsafe) static var blocked = Set<String>()
    nonisolated(unsafe) static var entered = Set<String>()
    nonisolated(unsafe) static var starts = [String]()
    nonisolated(unsafe) static var stops = [String]()
    static func configure(_ url: URL, _ rule: Rule = Rule(), held: Bool = false) {
        condition.lock(); defer { condition.unlock() }
        rules[url.path] = rule
        entered.remove(url.path)
        if held { blocked.insert(url.path) } else { blocked.remove(url.path) }
        starts.removeAll(); stops.removeAll()
    }
    static func release(_ url: URL) {
        condition.lock(); defer { condition.unlock() }
        blocked.remove(url.path); condition.broadcast()
    }
    static func hasEntered(_ url: URL) -> Bool {
        condition.lock(); defer { condition.unlock() }
        return entered.contains(url.path)
    }
    static func scope(_ url: URL, start: Bool) -> Bool {
        condition.lock(); defer { condition.unlock() }
        if start { starts.append(url.path) } else { stops.append(url.path) }
        return rules[url.path]?.scope ?? true
    }
    static func counts(_ url: URL) -> (Int, Int) {
        condition.lock(); defer { condition.unlock() }
        return (starts.filter { $0 == url.path }.count, stops.filter { $0 == url.path }.count)
    }
    static func awaitRule(_ url: URL) -> Rule {
        condition.lock(); defer { condition.unlock() }
        entered.insert(url.path); condition.broadcast()
        let deadline = Date().addingTimeInterval(10)
        while blocked.contains(url.path) {
            precondition(condition.wait(until: deadline), "Provider fixture timed out")
        }
        return rules[url.path] ?? Rule()
    }
}
extension URL {
    func testScopeStart() -> Bool { ProviderBoundary.scope(self, start: true) }
    func testScopeStop() { _ = ProviderBoundary.scope(self, start: false) }
}
final class NSFileCoordinator {
    init(filePresenter: Any?) {}
    func coordinate(readingItemAt url: URL, options: [Int], error: UnsafeMutablePointer<NSError?>?, byAccessor: (URL) -> Void) {
        let rule = ProviderBoundary.awaitRule(url)
        if rule.beforeError || rule.afterError {
            error?.pointee = NSError(domain: "ProviderBoundary", code: 701)
        }
        if !rule.beforeError && !rule.omitAccessor { byAccessor(rule.target ?? url) }
    }
}

@main struct FinalCoordination {
    @MainActor static func main() async throws {
        let fm = FileManager.default
        let root = fm.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try fm.createDirectory(at: root, withIntermediateDirectories: true)
        let suite = "FinalCoordination.\(UUID().uuidString)"
        let legacy = UserDefaults(suiteName: suite)!
        defer { try? fm.removeItem(at: root); legacy.removePersistentDomain(forName: suite) }
        let file = root.appendingPathComponent("settings.json")
        let input = root.appendingPathComponent("original.json")
        let accessor = root.appendingPathComponent("accessor.json")
        let missing = root.appendingPathComponent("missing.json")
        let store = SettingsStore(fileURL: file, legacy: legacy)
        let initial = store.value
        var imported = initial
        imported.server.listenPort = "24680"; imported.serverRunning = true
        try Data("not JSON".utf8).write(to: input)
        try imported.encoded().write(to: accessor)
        var checks = 0
        func check(_ condition: Bool, _ label: String) {
            checks += 1; precondition(condition, label)
        }
        func balanced(_ url: URL, _ start: Int = 1, _ stop: Int = 1) {
            let (a, b) = ProviderBoundary.counts(url)
            check(a == start && b == stop, "Acquired security scope balanced at original URL")
        }
        ProviderBoundary.configure(input, .init(target: accessor))
        try await store.importFile(input)
        check(store.value == imported, "Reads accessor URL, not requested URL")
        check(try AppSettings.decoded(Data(contentsOf: file)) == imported, "Redirected contents persisted")
        balanced(input)
        balanced(accessor, 0, 0)
        try store.importData(initial.encoded())
        for rule in [ProviderBoundary.Rule(target: accessor, beforeError: true),
                     .init(target: accessor, afterError: true), .init(omitAccessor: true),
                     .init(target: missing), .init()] {
            ProviderBoundary.configure(input, rule)
            let before = try Data(contentsOf: file)
            var rejected = false
            do { try await store.importFile(input) } catch { rejected = true }
            check(rejected && store.value == initial, "Coordinator/read failure preserves live settings")
            check(try Data(contentsOf: file) == before, "Coordinator/read failure preserves bytes")
            balanced(input)
        }
        ProviderBoundary.configure(input, .init(target: accessor, scope: false))
        try await store.importFile(input)
        check(store.value == imported, "False security-scope return does not forbid readable local file")
        balanced(input, 1, 0)
        try store.importData(initial.encoded())
        ProviderBoundary.configure(input, .init(target: accessor))
        let cancelled = Task { @MainActor in try await store.importFile(input) }
        cancelled.cancel()
        do { try await cancelled.value; preconditionFailure("Pre-cancelled import committed") } catch {}
        check(store.value == initial, "Pre-cancelled import preserves values")
        balanced(input, 0, 0)

        for action in 0..<8 {
            try store.importData(initial.encoded())
            ProviderBoundary.configure(input, .init(target: accessor), held: true)
            let task = Task { @MainActor in try await store.importFile(input) }
            for _ in 0..<1000 {
                if ProviderBoundary.hasEntered(input) { break }
                try await Task.sleep(for: .milliseconds(2))
            }
            check(ProviderBoundary.hasEntered(input), "Detached provider entered without blocking actor")
            switch action {
            case 0: store.set(\.serverRunning, false) // unchanged Stop still supersedes
            case 1: store.set(\.server.authPassword, "edited")
            case 2: store.set(\.selectedTab, .settings)
            case 3: do { try store.importData(Data("invalid".utf8)) } catch {}
            case 4: do { try await store.importFile(missing) } catch {}
            case 5: task.cancel()
            case 6: try store.importData(initial.encoded())
            default: store.set(\.serverRunning, true); store.set(\.serverRunning, false)
            }
            let live = store.value
            let bytes = try Data(contentsOf: file)
            ProviderBoundary.release(input)
            var rejected = false
            do { try await task.value } catch { rejected = true }
            check(rejected && store.value == live, "Slow import cannot reverse newer intent \(action)")
            check(try Data(contentsOf: file) == bytes, "Slow import cannot rewrite newer disk \(action)")
            balanced(input)
        }
        print("SUMMARY: \(checks) final coordination assertions; 0 failed; controlled OS boundaries, real store/files")
    }
}
