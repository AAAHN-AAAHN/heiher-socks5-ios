extension LoopAudioService {
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
