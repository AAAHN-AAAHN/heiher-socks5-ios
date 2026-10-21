import Foundation

// A blocking engine double with stop-before-start support; not a network simulation.
enum EngineProbe {
    static let condition = NSCondition()
    nonisolated(unsafe) static var stopped = false
    nonisolated(unsafe) static var nextResult: Int32?
    nonisolated(unsafe) static var starts = 0
    nonisolated(unsafe) static var active = 0
    nonisolated(unsafe) static var maximumActive = 0
    nonisolated(unsafe) static var configurations: [String] = []
    static func failNext(_ result: Int32) {
        condition.lock(); defer { condition.unlock() }
        nextResult = result
    }
    static func snapshot() -> (Int, Int, [String]) {
        condition.lock(); defer { condition.unlock() }
        return (starts, maximumActive, configurations)
    }
}
func hev_socks5_server_main_from_str(_ value: String, _ count: UInt32) -> Int32 {
    precondition(Int(count) == value.utf8.count)
    EngineProbe.condition.lock()
    EngineProbe.starts += 1
    EngineProbe.active += 1
    EngineProbe.maximumActive = max(EngineProbe.maximumActive, EngineProbe.active)
    EngineProbe.configurations.append(value)
    if let result = EngineProbe.nextResult {
        EngineProbe.nextResult = nil
        EngineProbe.active -= 1
        EngineProbe.condition.unlock()
        return result
    }
    while !EngineProbe.stopped { EngineProbe.condition.wait() }
    EngineProbe.stopped = false
    EngineProbe.active -= 1
    EngineProbe.condition.unlock()
    return 0
}
func hev_socks5_server_quit() {
    EngineProbe.condition.lock()
    EngineProbe.stopped = true
    EngineProbe.condition.broadcast()
    EngineProbe.condition.unlock()
}

func hev_socks5_server_prepare() {
    EngineProbe.condition.lock()
    precondition(EngineProbe.active == 0)
    EngineProbe.stopped = false
    EngineProbe.condition.unlock()
}
