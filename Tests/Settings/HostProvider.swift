import Foundation

// Linux has no document provider API. These boundaries supply a regular URL;
// production reads, validation, atomic writes and rollback execute intact.
#if os(Linux)
final class NSFileCoordinator {
    init(filePresenter: Any?) {}
    func coordinate(readingItemAt url: URL, options: [Int],
                    error: UnsafeMutablePointer<NSError?>?, byAccessor: (URL) -> Void) {
        byAccessor(url)
    }
}
extension URL {
    func startAccessingSecurityScopedResource() -> Bool { true }
    func stopAccessingSecurityScopedResource() {}
}
#endif
