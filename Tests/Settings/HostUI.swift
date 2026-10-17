import Foundation

// Host-only UI boundaries. Apple runs use SwiftUI/Combine themselves; Linux runs
// retain synchronous subscription/reentry while executing the actual store body.
#if os(Linux)
protocol ObservableObject {}
@propertyWrapper struct Published<Value> { var wrappedValue: Value }
struct Binding<Value> {
    let get: () -> Value
    let set: (Value) -> Void
    init(get: @escaping () -> Value, set: @escaping (Value) -> Void) {
        self.get = get; self.set = set
    }
    var wrappedValue: Value { get { get() } nonmutating set { set(newValue) } }
}

@MainActor final class HostSubscription {
    private var action: (() -> Void)?
    init(_ action: @escaping () -> Void) { self.action = action }
    func cancel() { action?(); action = nil }
}

@MainActor final class ObservableObjectPublisher {
    private var nextID = 0
    private var observers: [(id: Int, callback: (()) -> Void)] = []
    func sink(_ callback: @escaping (()) -> Void) -> HostSubscription {
        let id = nextID; nextID += 1
        observers.append((id, callback))
        return HostSubscription { [weak self] in self?.observers.removeAll { $0.id == id } }
    }
    func send() {
        let current = observers
        for observer in current { observer.callback(()) }
    }
}
#endif
