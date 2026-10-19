// Test-only value observations and queue fences; shipping code has no hooks.
struct FinalizationControl: Sendable {
    let on: Bool
    let epoch: UInt64
    let retryAt: Double
    let assetBlocked: Bool
    let operation: UInt64?
    let completed: UInt64
    let maximumOutstanding: Int
    let timerActive: Bool
}

extension LoopAudioService {
    func auditFinalizationFence(_ completion: @escaping @Sendable (FinalizationControl) -> Void) {
        queueOwner.auditFinalizationFence(completion)
    }
    func auditSetPlayerGeneration(_ value: UInt64, _ completion: @escaping @Sendable () -> Void) {
        queueOwner.auditSetPlayerGeneration(value, completion)
    }
    func auditPlayerGeneration(_ completion: @escaping @Sendable (UInt64?) -> Void) {
        queueOwner.auditPlayerGeneration(completion)
    }
}

extension LoopAudioQueueOwner {
    func auditFinalizationFence(_ completion: @escaping @Sendable (FinalizationControl) -> Void) {
        control.async { [self] in
            io.async { [self] in
                control.async { [self] in
                    lock.lock()
                    let next = ticket
                    lock.unlock()
                    completion(FinalizationControl(on: next.on, epoch: next.epoch,
                        retryAt: retryAt, assetBlocked: assetBlocked, operation: work?.id,
                        completed: completed, maximumOutstanding: peakOutstanding, timerActive: timer != nil))
                }
            }
        }
    }
    func auditSetPlayerGeneration(_ value: UInt64, _ completion: @escaping @Sendable () -> Void) {
        io.async { [self] in
            (endpoint as? AudioEndpoint)?.auditSetGeneration(value)
            completion()
        }
    }
    func auditPlayerGeneration(_ completion: @escaping @Sendable (UInt64?) -> Void) {
        io.async { [self] in completion((endpoint as? AudioEndpoint)?.auditGeneration) }
    }
}

extension AudioEndpoint {
    func auditSetGeneration(_ value: UInt64) { generation = value }
    var auditGeneration: UInt64 { generation }
}
