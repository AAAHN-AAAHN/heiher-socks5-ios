import os

final class CheckedLockProbe: Sendable {
    private let state = OSAllocatedUnfairLock(initialState: 0)

    func take() -> Int {
        state.withLock { value in
            value += 1
            return value
        }
    }
}
