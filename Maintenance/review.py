"""Small audited corrections to the previously delivered sources; not runtime code."""
from pathlib import Path
import subprocess

OLD = 'b68dbb9ca7d4d028111666915eba951911857b1d'


def prepare(repo, templates, workspace):
    root = workspace / 'reviewed-Socks5'
    tests = templates / 'Tests/Settings'
    for prefix, target in [('Socks5', root), ('Tests/Settings', tests)]:
        names = subprocess.check_output(['git', '-C', str(repo), 'ls-tree', '-r', '--name-only', OLD, prefix]).decode().splitlines()
        for name in names:
            path = target / Path(name).relative_to(prefix)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(subprocess.check_output(['git', '-C', str(repo), 'show', OLD + ':' + name]))

    def replace(path, before, after):
        p = root / path
        text = p.read_text()
        assert text.count(before) == 1, (path, before)
        p.write_text(text.replace(before, after))

    replace('Server/ServerController.swift', '    private var stopping = false',
            '    private var stopping = false\n    private var attempted: ServerSettings?')
    replace('Server/ServerController.swift', 'func apply(_ settings: AppSettings) {',
            'func apply(_ settings: AppSettings, retry: Bool = false) {')
    replace('Server/ServerController.swift',
            '        desired = settings.serverRunning ? settings.server : nil',
            '        desired = settings.serverRunning ? settings.server : nil\n        if desired == nil { attempted = nil }')
    replace('Server/ServerController.swift', '        startDesired()\n    }',
            '        if desired == nil || retry || desired != attempted { startDesired() }\n    }')
    replace('Server/ServerController.swift', '    private func startDesired() {\n        guard let desired',
            '    private func startDesired() {\n        attempted = desired\n        guard let desired')
    p = root / 'ContentView.swift'
    p.write_text(p.read_text().replace('server.apply(settings.value)', 'server.apply(settings.value, retry: true)', 1))
    replace('Settings/AppSettings.swift', '        return try encoder.encode(self)',
            '        let data = try encoder.encode(self)\n        guard data.count <= 65_536 else { throw SettingsError.invalid("Settings file exceeds 64 KB.") }\n        return data')
    replace('Settings/AppSettings.swift', '.rangeOfCharacter(from: .controlCharacters)',
            '.rangeOfCharacter(from: .controlCharacters.union(.newlines))')
    replace('Settings/SettingsStore.swift', 'value = try AppSettings.decoded(Data(contentsOf: self.fileURL))',
            'value = try AppSettings.decoded(Self.read(self.fileURL))')
    replace('Settings/SettingsStore.swift', '''                result = Result {
                    let file = try FileHandle(forReadingFrom: url)
                    defer { try? file.close() }
                    return try file.read(upToCount: 65_537) ?? Data()
                }''', '                result = Result { try Self.read(url) }')
    replace('Settings/SettingsStore.swift', '    private func write(_ value: AppSettings) throws {',
            '''    private nonisolated static func read(_ url: URL) throws -> Data {
        let file = try FileHandle(forReadingFrom: url)
        defer { try? file.close() }
        return try file.read(upToCount: 65_537) ?? Data()
    }

    private func write(_ value: AppSettings) throws {''')
    replace('BackgroundKeepAlive/BackgroundKeepAlive.swift',
            '/// Background services; SettingsStore owns persistence and user intent.',
            '/// Background services; the app root supplies persisted user intent.')
    (root / 'BackgroundKeepAlive/BackgroundKeepAliveView.swift').write_bytes(
        (templates / 'BackgroundKeepAliveView.swift').read_bytes())
    (root / 'Info.plist').write_bytes((root / 'BackgroundKeepAlive/Info.plist').read_bytes())
    (root / 'BackgroundKeepAlive/Info.plist').unlink()
    subprocess.run(['git', '-C', str(tests), 'apply', '--unsafe-paths', str(templates / 'reviewed-tests.patch')], check=True)
    p = tests / 'ServerTests.swift'
    marker = '        print("PASS: explicit retry and a completed Stop/Start each start exactly once")'
    text = p.read_text()
    assert text.count(marker) == 1
    p.write_text(text.replace(marker, marker + '''
        value.serverRunning = true
        value.server.listenPort = "invalid"
        server.apply(value)
        value.serverRunning = false
        server.apply(value)
        precondition(server.status == "Stopped" && !server.isRunning)
        print("PASS: Stop clears a failed configuration status without launching")'''))
