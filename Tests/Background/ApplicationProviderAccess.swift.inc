// Appended to the copied lease file by the host fixture driver only. The
// wrappers hold actual issue/receipt boundaries without changing their meaning.
extension RecoveryExecutionLease.Provider {
    func auditBeforeIssue(_ before: @escaping @Sendable () -> Void) -> Self {
        Self(issue: { allowed, expire, receipt, returned in
            before()
            self.issue(allowed, expire, receipt, returned)
        }, end: end)
    }
    func auditBeforeReceipt(_ before: @escaping @Sendable () -> Void) -> Self {
        Self(issue: { allowed, expire, receipt, returned in
            self.issue(allowed, expire, { id in before(); receipt(id) }, returned)
        }, end: end)
    }
}
