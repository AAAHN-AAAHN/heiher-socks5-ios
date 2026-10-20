import Foundation

// Deterministic file-provider scheduling only; reads/writes and JSON remain real.
enum CoordinationProbe {
    static let condition = NSCondition()
    nonisolated(unsafe) static var blocked = Set<String>()
    nonisolated(unsafe) static var entered = Set<String>()
    nonisolated(unsafe) static var exited = Set<String>()
    static func block(_ path: String) {
        condition.lock(); defer { condition.unlock() }
        blocked.insert(path); entered.remove(path); exited.remove(path)
    }
    static func release(_ path: String) {
        condition.lock(); defer { condition.unlock() }
        blocked.remove(path); condition.broadcast()
    }
    static func hasEntered(_ path: String) -> Bool {
        condition.lock(); defer { condition.unlock() }
        return entered.contains(path)
    }
    static func wait(_ path: String) {
        condition.lock(); defer { condition.unlock() }
        entered.insert(path); condition.broadcast()
        let deadline = Date().addingTimeInterval(10)
        while blocked.contains(path) {
            guard condition.wait(until: deadline) else { fatalError("Test coordination timeout") }
        }
    }
}
final class NSFileCoordinator {
    init(filePresenter: Any?) {}
    func coordinate(readingItemAt url: URL, options: [Int], error: UnsafeMutablePointer<NSError?>?, byAccessor: (URL) -> Void) {
        CoordinationProbe.wait(url.path)
        byAccessor(url)
    }
}
#if os(Linux)
extension URL {
    func startAccessingSecurityScopedResource() -> Bool { true }
    func stopAccessingSecurityScopedResource() {}
}
#endif
