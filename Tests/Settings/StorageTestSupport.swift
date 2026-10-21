import Foundation

/// Tests name their actual durability boundary. Creating a store alone starts an
/// asynchronous read and cannot be used as proof that persisted values were read.
@MainActor func loadedSettings(fileURL: URL, legacy: UserDefaults = .standard) async -> SettingsStore {
    let store = SettingsStore(fileURL: fileURL, legacy: legacy)
    await store.whenLoaded()
    return store
}
