#if !canImport(Combine)
protocol ObservableObject: AnyObject {
    associatedtype ObjectWillChangePublisher = ObservableObjectPublisher
    var objectWillChange: ObjectWillChangePublisher { get }
}
final class ObservableObjectPublisher {
    @MainActor var receive: (() -> Void)?
    @MainActor init() {}
    @MainActor func send() { receive?() }
}
#endif
