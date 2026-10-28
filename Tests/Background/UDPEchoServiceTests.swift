import Foundation

@main
struct UDPEchoServiceTests {
    static func main() async throws {
        try parser()
        try await storage()
        try await model()
        print("PASS: UDP Echo target policy, strict storage, latest intent and publication")
    }

    static func parser() throws {
        let input = PeriodicUDPEchoSettings(enabled: true,
            destinations: " 1.2.3.4,::ffff:1.2.3.4\r\n::1\u{2028}2001:db8::1 ", period: " 7 ")
        let plan = try PeriodicUDPEchoService.parse(input)
        precondition(plan.interval == 7_000_000)
        precondition(plan.targets[0].map(\.host) == ["1.2.3.4"])
        precondition(plan.targets[1].map(\.host) == ["::1", "2001:db8::1"])
        precondition(plan.targets.flatMap { $0 }.allSatisfy { $0.port == 7 })
        for host in ["", "example.com", "127.0.0.1:7", "fe80::1%lo", "fe80::1", "1.1.1.1\u{0}"] {
            do {
                _ = try PeriodicUDPEchoService.parse(.init(enabled: true, destinations: host, period: "1"))
                preconditionFailure("Invalid address accepted")
            } catch PeriodicUDPEchoService.InputError.invalid {}
        }
        for period in ["", "0", "-1", "+1", "0.5", "NaN", "18446744073709551615"] {
            do {
                _ = try PeriodicUDPEchoService.parse(.init(enabled: true, destinations: "::1", period: period))
                preconditionFailure("Invalid period accepted")
            } catch PeriodicUDPEchoService.InputError.invalid {}
        }
        let many = (0..<65_536).map { "10.\($0 >> 8).\($0 & 255).1" }.joined(separator: ",")
        let maximum = try PeriodicUDPEchoService.parse(.init(enabled: true, destinations: many, period: "1"))
        precondition(maximum.targets[0].count == 65_536)
        do {
            _ = try PeriodicUDPEchoService.parse(.init(enabled: true, destinations: many + ",11.0.0.1", period: "1"))
            preconditionFailure("Unique target limit not enforced")
        } catch PeriodicUDPEchoService.InputError.invalid {}
        let duplicate = String(repeating: "1.1.1.1,\n", count: 100_000)
        let repeated = try PeriodicUDPEchoService.parse(.init(enabled: true, destinations: duplicate, period: "1"))
        precondition(repeated.targets[0].count == 1)
        let longPeriod = String(repeating: "0", count: 250_000) + "1"
        let longValue = try PeriodicUDPEchoService.parse(.init(enabled: true, period: longPeriod))
        precondition(longValue.interval == 1_000_000)
        var checks = 0
        do {
            _ = try PeriodicUDPEchoService.parse(.init(enabled: true, period: longPeriod), isCurrent: {
                checks += 1
                return checks < 3
            })
            preconditionFailure("Long period parsing ignored cancellation")
        } catch PeriodicUDPEchoService.InputError.cancelled {}
        do {
            _ = try PeriodicUDPEchoService.parse(.init(enabled: true, destinations: many, period: "1"),
                                                isCurrent: { false })
            preconditionFailure("Cancelled parsing continued")
        } catch PeriodicUDPEchoService.InputError.cancelled {}
        let a = PeriodicUDPEchoSettings(destinations: "\u{e9}")
        let b = PeriodicUDPEchoSettings(destinations: "e\u{301}")
        precondition(a != b)
    }

    static func load(_ store: PeriodicUDPEchoStore) async -> Result<PeriodicUDPEchoSettings?, Error> {
        await withCheckedContinuation { continuation in store.load { continuation.resume(returning: $0) } }
    }

    static func save(_ value: PeriodicUDPEchoSettings, to store: PeriodicUDPEchoStore) async throws {
        let result: Result<Void, Error> = await withCheckedContinuation { continuation in
            store.save(value) { continuation.resume(returning: $0) }
        }
        try result.get()
    }

    static func storage() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let url = directory.appendingPathComponent("periodic-udp-echo.json")
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = PeriodicUDPEchoStore(url: url)
        let missing = try await load(store).get()
        precondition(missing == nil)
        let value = PeriodicUDPEchoSettings(enabled: false,
            destinations: String(repeating: "1.1.1.1,\r\n", count: 20_000) + "e\u{301}", period: "")
        try await save(value, to: store)
        let restored = try await load(store).get()
        precondition(restored == value)
        let data = try Data(contentsOf: url)
        precondition(data.count > 65_536)
        for invalid in ["null", "{}", #"{"enabled":null,"destinations":"","period":"1"}"#,
                        #"{"enabled":false,"destinations":7,"period":"1"}"#] {
            try Data(invalid.utf8).write(to: url, options: .atomic)
            if case .success = await load(store) { preconditionFailure("Malformed settings accepted") }
        }
        let delayed = DispatchQueue(label: "echo.store.delayed")
        delayed.suspend()
        let coalesced = PeriodicUDPEchoStore(url: url, queue: delayed)
        for index in 0..<100 {
            coalesced.save(.init(period: String(index))) { _ in preconditionFailure("Superseded save executed") }
        }
        let final = PeriodicUDPEchoSettings(period: "12345")
        let completion: Result<Void, Error> = await withCheckedContinuation { continuation in
            coalesced.save(final) { continuation.resume(returning: $0) }
            delayed.resume()
        }
        try completion.get()
        let latest = try await load(coalesced).get()
        precondition(latest == final)
    }

    @MainActor
    static func model() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("periodic-udp-echo.json")
        try JSONEncoder().encode(PeriodicUDPEchoSettings(enabled: true)).write(to: url)
        let queue = DispatchQueue(label: "echo.model.delayed-load")
        queue.suspend()
        let model = PeriodicUDPEchoModel(store: PeriodicUDPEchoStore(url: url, queue: queue))
        model.setEnabled(false)
        let old = model.intentRevision
        model.setDestinations("2001:db8::1,\r\n1.1.1.1")
        model.restore(.init(enabled: true), ifRevision: old)
        precondition(!model.enabled)
        queue.resume()
        for _ in 0..<200 where model.savePending { try await Task.sleep(for: .milliseconds(5)) }
        precondition(!model.savePending && model.storageError == nil && !model.enabled)
        let stored = try JSONDecoder().decode(PeriodicUDPEchoSettings.self, from: Data(contentsOf: url))
        precondition(stored == model.settings)
        precondition(!stored.enabled && stored.destinations == "2001:db8::1,\r\n1.1.1.1")

        var calls = [PeriodicUDPEchoSettings]()
        var reentrant: PeriodicUDPEchoModel!
        reentrant = PeriodicUDPEchoModel(store: nil, save: { value in
            calls.append(value)
            if value.enabled { reentrant.setEnabled(false) }
        })
        reentrant.setEnabled(true)
        precondition(!reentrant.enabled && reentrant.state == "Off")
        precondition(calls.count == 2 && calls[0].enabled && !calls[1].enabled)
        reentrant.restore(.init(destinations: "", period: ""))
        precondition(reentrant.destinations.isEmpty && reentrant.period.isEmpty)
        precondition(calls.count == 2)
    }
}
