// Test-only, value-only read on the original control queue. Never mutates policy.
extension LoopAudioService {
    func auditIngressSnapshot(_ completion: @escaping @Sendable (IngressSnapshot) -> Void) {
        queueOwner.auditIngressSnapshot(completion)
    }
}

extension LoopAudioQueueOwner {
    func auditIngressSnapshot(_ completion: @escaping @Sendable (IngressSnapshot) -> Void) {
        control.async { [self] in
            lock.lock()
            let pending = inbox.invalidated
            let latestEpoch = ticket.epoch
            lock.unlock()
            let name: String?
            switch work?.command {
            case .start?: name = "start"
            case .inspect?: name = "inspect"
            case .stop?: name = "stop"
            case nil: name = nil
            }
            completion(IngressSnapshot(on: current.on, epoch: current.epoch, latestEpoch: latestEpoch, playing: playing,
                rebuild: rebuild, episode: episode, operation: work?.id, command: name,
                invalidationPending: pending, completed: completed, timerActive: timer != nil,
                maximumOutstanding: peakOutstanding))
        }
    }
}
