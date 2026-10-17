import Foundation

// Host-only UI boundaries. Apple runs use SwiftUI/Combine themselves; Linux runs
// retain synchronous subscription/reentry while executing the actual store body.
#if os(Linux)
protocol ObservableObject: AnyObject {
    associatedtype ObjectWillChangePublisher = ObservableObjectPublisher
    var objectWillChange: ObjectWillChangePublisher { get }
}
extension ObservableObject where ObjectWillChangePublisher == ObservableObjectPublisher {
    // The inherited @Published controller and historical stores need Combine's
    // default witness, but these hosts do not model their implicit publication.
    // Current SettingsStore must use its own concrete, persistent publisher.
    var objectWillChange: ObservableObjectPublisher {
        preconditionFailure("Implicit @Published publication is outside this host boundary")
    }
}
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

// Combine's publisher is not Sendable. Isolating the whole mock class would
// silently make its type Sendable and hide the stored-let conformance boundary.
final class ObservableObjectPublisher {
    @MainActor private var nextID = 0
    @MainActor private var observers: [(id: Int, callback: (()) -> Void)] = []
    @MainActor init() {}
    @MainActor func sink(_ callback: @escaping (()) -> Void) -> HostSubscription {
        let id = nextID; nextID += 1
        observers.append((id, callback))
        return HostSubscription { [weak self] in self?.observers.removeAll { $0.id == id } }
    }
    @MainActor func send() {
        let current = observers
        for observer in current { observer.callback(()) }
    }
}
#endif
