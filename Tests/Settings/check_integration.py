#!/usr/bin/env python3
"""Static integration checks supplement the controller tests and actual iOS build."""
from pathlib import Path
import json
import re
import struct

root = Path(__file__).resolve().parents[2]
view = (root / 'Socks5/BackgroundKeepAlive/BackgroundKeepAliveView.swift').read_text()
assert re.findall(r'\.tag\(AppSettings.Tab\.(\w+)\)', view) == ['statistics', 'server', 'background', 'settings']
assert '.onChange(of: settings.value, initial: true)' in view
for name in ['interruptionNotification', 'routeChangeNotification', 'mediaServicesWereLostNotification', 'mediaServicesWereResetNotification']:
    assert name in view
server = (root / 'Socks5/ContentView.swift').read_text()
for name in ['workers', 'listenAddress', 'listenPort', 'udpListenAddress', 'udpListenPort',
             'bindIPv4Address', 'bindIPv6Address', 'bindInterface', 'authUsername',
             'authPassword', 'listenIPv6Only']:
    assert f'settings.binding(\\.server.{name})' in server, name
assert '@State private' not in server
controller = (root / 'Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift').read_text()
assert 'UserDefaults' not in controller and 'retryDelay' not in controller
assert 'scheduleAudioCheck(after: 5)' not in controller
assert 'scheduleAudioCheck(after: 2)' in controller and 'scheduleAudioCheck(after: 1)' in controller
assert 'AVAudioSession.InterruptionType' not in controller
asset = root / 'Socks5/Assets.xcassets/AppIcon.appiconset'
icon = json.loads((asset / 'Contents.json').read_text())['images'][0]['filename']
png = (asset / icon).read_bytes()
assert png[:8] == b'\x89PNG\r\n\x1a\n'
assert struct.unpack('>II', png[16:24]) == (1024, 1024)
assert png[25] in (2, 3) and b'tRNS' not in png  # Opaque RGB or lossless palette PNG.
print('PASS: four saved tabs, all 11 server fields, root-owned event observers, fixed audio intervals, 1024px opaque icon')

project = (root / 'Socks5.xcodeproj/project.pbxproj').read_text()
keys = re.findall(r'^\s*([A-F0-9]{24}) /\*.*?\*/ = \{', project, re.M)
assert len(keys) == len(set(keys)), 'Duplicate project object ID'
print('PASS: Xcode file, group and source entries have unique object IDs')
