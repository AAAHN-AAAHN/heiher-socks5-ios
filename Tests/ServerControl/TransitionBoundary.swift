import Foundation

// Test-only scheduler: hold the exact production worker closure until the test
// permits its return. Actor completion is still the real asynchronous Task.
enum DispatchQueue {
    enum QoS { case utility }
    struct Queue {
        func async(execute: @escaping @Sendable () -> Void) {
            precondition(TransitionBoundary.pending == nil, "Overlapping engine dispatch")
            TransitionBoundary.pending = execute
            TransitionBoundary.dispatches += 1
        }
    }
    static func global(qos: QoS) -> Queue { Queue() }
}

enum TransitionBoundary {
    nonisolated(unsafe) static var pending: (@Sendable () -> Void)?
    nonisolated(unsafe) static var dispatches = 0
    nonisolated(unsafe) static var prepares = 0
    nonisolated(unsafe) static var quits = 0
    nonisolated(unsafe) static var result: Int32 = 0
    nonisolated(unsafe) static var lastConfiguration = ""

    static func reset() {
        precondition(pending == nil)
        dispatches = 0; prepares = 0; quits = 0
        result = 0; lastConfiguration = ""
    }

    static func finish(_ code: Int32) {
        precondition(pending != nil)
        result = code
        let work = pending
        pending = nil
        work?()
    }
}

func hev_socks5_server_prepare() {
    precondition(TransitionBoundary.pending == nil, "Prepare while previous invocation owns work")
    TransitionBoundary.prepares += 1
}

func hev_socks5_server_quit() { TransitionBoundary.quits += 1 }

func hev_socks5_server_main_from_str(_ text: String, _ length: UInt32) -> Int32 {
    precondition(Int(length) == text.utf8.count)
    TransitionBoundary.lastConfiguration = text
    return TransitionBoundary.result
}
