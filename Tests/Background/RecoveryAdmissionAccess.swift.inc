extension LoopAudioService {
    // Test access remains a value-only method on the checked facade.
    func auditStopAdmission(owner: UInt64, direct: Bool, result: @escaping @Sendable (Bool) -> Void) {
        queueOwner.auditStopAdmission(owner: owner, direct: direct, result: result)
    }
    func auditAfterWorkerTurn(_ completion: @escaping @Sendable () -> Void) {
        queueOwner.auditAfterWorkerTurn(completion)
    }
    func auditHoldControl(entered: @escaping @Sendable () -> Void, release: DispatchSemaphore) {
        queueOwner.auditHoldControl(entered: entered, release: release)
    }
    func auditHoldIO(entered: @escaping @Sendable () -> Void, release: DispatchSemaphore) {
        queueOwner.auditHoldIO(entered: entered, release: release)
    }
    func auditAfterIO(_ completion: @escaping @Sendable () -> Void) {
        queueOwner.auditAfterIO(completion)
    }
}

extension LoopAudioQueueOwner {
    func auditAfterWorkerTurn(_ completion: @escaping @Sendable () -> Void) {
        let io = self.io
        control.async { io.async(execute: completion) }
    }
    func auditHoldControl(entered: @escaping @Sendable () -> Void, release: DispatchSemaphore) {
        control.async {
            entered()
            precondition(release.wait(timeout: .now() + 3) == .success, "TEST_CONTROL_HOLD_NOT_RELEASED")
        }
    }
    func auditHoldIO(entered: @escaping @Sendable () -> Void, release: DispatchSemaphore) {
        io.async {
            entered()
            precondition(release.wait(timeout: .now() + 3) == .success, "TEST_IO_HOLD_NOT_RELEASED")
        }
    }
    func auditAfterIO(_ completion: @escaping @Sendable () -> Void) {
        io.async(execute: completion)
    }
    // Test-only control-lane admission. Appended by the host test driver only.
    func auditStopAdmission(owner: UInt64, direct: Bool, result: @escaping @Sendable (Bool) -> Void) {
        control.async { [self] in
            if work != nil {
                control.asyncAfter(deadline: .now() + 0.001) { [self] in
                    auditStopAdmission(owner: owner, direct: direct, result: result)
                }
                return
            }
            cancelTimer()
            setEnabled(false, owner: owner)
            setEnabled(true, owner: owner)
            if direct { begin(.inspect) } else { tick() }
            if case .stop? = work?.command { result(true) }
            else { result(releaseBarrier) }
        }
    }
}
