#!/usr/bin/env python3
"""Actual Xcode asset compilation and Simulator app registration, never IPA/archive.

The simulator app is the unchanged product, using its committed native framework.
Only a second installed test copy's bundle ID is changed. This is not SideStore or
LiveContainer execution and does not certify SpringBoard tinted/clear appearances.
"""
import json
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import time

from check_icon import ROOT, CATALOG, IMAGE_HASH, require

OUT = ROOT / 'artifacts/icon-checks'
WORK = ROOT / '.build/icon-checks'


def run(*args, timeout=120):
    command = [str(a) for a in args]
    with (OUT / 'commands.log').open('a') as log:
        log.write(json.dumps(command) + '\n')
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        with (OUT / 'commands.log').open('a') as log:
            log.write(f'TIMEOUT after {timeout}s; command did not complete.\n')
        raise
    with (OUT / 'commands.log').open('a') as log:
        log.write(result.stderr + f'\nexit={result.returncode}\n')
    if result.returncode:
        raise RuntimeError(f'{command}: {result.returncode}\n{result.stdout}\n{result.stderr}')
    return result.stdout.strip()


def compiled(folder, info):
    require((folder / 'Assets.car').is_file(), 'Missing compiled asset catalog')
    for key in ('CFBundleIcons', 'CFBundleIcons~ipad'):
        primary = info[key]['CFBundlePrimaryIcon']
        require(primary['CFBundleIconName'] == 'AppIcon', key)
        require(primary.get('CFBundleIconFiles'), 'Missing legacy filename fallback')
        for name in primary['CFBundleIconFiles']:
            require(isinstance(name, str) and name and Path(name).name == name,
                    'Icon reference must be a nonempty basename')
            pattern = re.escape(name) + r'(?:@[123]x)?(?:~(?:iphone|ipad))?\.png'
            candidates = [path for path in folder.glob('*.png')
                          if path.is_file() and re.fullmatch(pattern, path.name)]
            require(bool(candidates), 'No generated file for ' + name)
        require(not info[key].get('CFBundleAlternateIcons'), 'Unexpected alternate icons')
    images = sorted(path for path in folder.glob('AppIcon*.png') if path.is_file())
    require(bool(images), 'No generated icon PNG')
    return images


def catalog_renditions(items):
    icons = [item for item in items
             if item.get('Name') == 'AppIcon' and item.get('AssetType') == 'Icon Image']
    require({item.get('Idiom') for item in icons} >= {'phone', 'pad'},
            'CAR missing phone/pad AppIcon images')
    require(all(item.get('PixelWidth') == 1024 and item.get('PixelHeight') == 1024
                and item.get('Opaque') is True for item in icons),
            'CAR AppIcon dimensions/opacity differ from the source contract')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # Direct retries must not retain a previous successful install verdict.
    for marker in ('SUCCESS.txt', 'simulator-results.json'):
        (OUT / marker).unlink(missing_ok=True)
    require(__debug__, 'Run the audit without Python optimization')
    run('git', 'diff', '--exit-code', 'HEAD', '--')
    run('git', 'diff', '--cached', '--exit-code', 'HEAD', '--')
    WORK.mkdir(parents=True, exist_ok=True)
    require(run('xcrun', '--sdk', 'iphoneos', '--show-sdk-version').startswith('27.'), 'Wrong SDK')
    toolchain = run('xcodebuild', '-version') + '\n' + run('xcrun', '--sdk', 'iphoneos', '--show-sdk-version')
    (OUT / 'toolchain.txt').write_text(toolchain + '\n' + run('sw_vers') + '\n' + run('xcrun', 'swiftc', '--version') + '\n')
    for configuration in ('Debug', 'Release'):
        settings_text = run('xcodebuild', '-project', ROOT / 'Socks5.xcodeproj', '-scheme', 'Socks5',
                            '-configuration', configuration, '-sdk', 'iphoneos', '-showBuildSettings', '-json')
        settings = json.loads(settings_text)
        (OUT / (configuration + '-settings.json')).write_text(settings_text + '\n')
        target = next(t['buildSettings'] for t in settings if t['target'] == 'Socks5')
        for key, expected in [('ASSETCATALOG_COMPILER_APPICON_NAME', 'AppIcon'),
                              ('IPHONEOS_DEPLOYMENT_TARGET', '17.2'), ('PRODUCT_BUNDLE_IDENTIFIER', 'hev.Socks5'),
                              ('TARGETED_DEVICE_FAMILY', '1,2'), ('INFOPLIST_FILE', 'Socks5/Info.plist')]:
            require(target[key] == expected, configuration + ': ' + key)
        require(not target.get('CODE_SIGN_ENTITLEMENTS'), 'Unexpected entitlement file')
    device_assets = OUT / 'iphoneos-assets'; device_assets.mkdir()
    # Compile the real catalog for both target families and the real minimum OS.
    report = run('xcrun', 'actool', ROOT / 'Socks5/Assets.xcassets', '--compile', device_assets,
                 '--platform', 'iphoneos', '--minimum-deployment-target', '17.2', '--app-icon', 'AppIcon',
                 '--target-device', 'iphone', '--target-device', 'ipad', '--compress-pngs',
                 '--output-partial-info-plist', device_assets / 'asset-info.plist',
                 '--output-format', 'xml1', '--warnings', '--notices')
    (OUT / 'actool.plist').write_text(report)
    diagnostics = plistlib.loads(report.encode())
    require(not any(value for key, value in diagnostics.items() if key.endswith(('.errors', '.warnings'))),
            'Asset compiler warnings/errors require inspection')
    info = plistlib.loads((device_assets / 'asset-info.plist').read_bytes())
    device_images = compiled(device_assets, info)
    assetinfo = run('xcrun', 'assetutil', '--info', device_assets / 'Assets.car')
    (OUT / 'assets-info.json').write_text(assetinfo + '\n')
    catalog_renditions(json.loads(assetinfo))
    decoder = WORK / 'decode-images'
    run('xcrun', 'swiftc', '-parse-as-library', '-swift-version', '5', '-warnings-as-errors',
        ROOT / 'Tests/AppIcon/DecodeImages.swift', '-o', decoder)
    decoded = run(decoder, ROOT / CATALOG / 'AppIcon.png', *device_images)
    (OUT / 'imageio-decoded.json').write_text(decoded + '\n')
    require(json.loads(decoded)[0]['fileSHA256'] == IMAGE_HASH, 'Decoder used different artwork')
    # Build only a Simulator .app. No iPhone archive, native rebuild or IPA.
    with (OUT / 'simulator-build.log').open('w') as log:
        subprocess.run(['xcodebuild', 'build', '-project', str(ROOT / 'Socks5.xcodeproj'), '-scheme', 'Socks5',
                        '-configuration', 'Release', '-sdk', 'iphonesimulator', '-arch', 'arm64',
                        'CONFIGURATION_BUILD_DIR=' + str(WORK / 'simulator'), 'CODE_SIGNING_ALLOWED=NO',
                        'SWIFT_TREAT_WARNINGS_AS_ERRORS=YES'], stdout=log, stderr=subprocess.STDOUT,
                       check=True, timeout=300, cwd=ROOT)
    app = WORK / 'simulator/Socks5.app'
    app_info = plistlib.loads((app / 'Info.plist').read_bytes())
    require(app_info['DTSDKName'].startswith('iphonesimulator27.'), 'Wrong Simulator SDK')
    require(app_info['MinimumOSVersion'] == '17.2' and not app_info.get('UIBackgroundModes'), 'Changed app scope')
    compiled(app, app_info)
    (OUT / 'simulator-Info.plist').write_bytes((app / 'Info.plist').read_bytes())
    simdecoded = run(decoder, *sorted(app.glob('AppIcon*.png')))
    (OUT / 'simulator-images.json').write_text(simdecoded + '\n')
    run('python3', ROOT / 'Build/check.py', 'package', app)
    runtimes = json.loads(run('xcrun', 'simctl', 'list', 'runtimes', '-j'))['runtimes']
    runtime = next(r for r in runtimes if r['isAvailable'] and r['identifier'].startswith('com.apple.CoreSimulator.SimRuntime.iOS-27'))
    device = run('xcrun', 'simctl', 'create', 'App Icon Review',
                 'com.apple.CoreSimulator.SimDeviceType.iPhone-16', runtime['identifier'])
    (OUT / 'runtime.json').write_text(json.dumps(runtime, indent=2) + '\n')
    results = []
    try:
        run('xcrun', 'simctl', 'boot', device)
        (OUT / 'boot.log').write_text(run('xcrun', 'simctl', 'bootstatus', device, '-b', timeout=240))
        for identity in ('hev.Socks5', 'hev.Socks5.ICONREVIEW'):
            label = 'original' if identity == 'hev.Socks5' else 'remapped'
            testapp = WORK / (label + '/Socks5.app')
            shutil.copytree(app, testapp)
            changed_info = dict(app_info, CFBundleIdentifier=identity)
            (testapp / 'Info.plist').write_bytes(plistlib.dumps(changed_info))
            run('codesign', '--force', '--sign', '-', testapp)
            run('xcrun', 'simctl', 'install', device, testapp)
            listing_path = OUT / (label + '-all-registrations.plist')
            listing_path.write_text(run('xcrun', 'simctl', 'listapps', device))
            listing = json.loads(run('plutil', '-convert', 'json', '-o', '-', listing_path))
            require(identity in listing, 'Simulator registration missing')
            (OUT / (label + '-registration.plist')).write_bytes(plistlib.dumps(listing[identity]))
            installed = Path(run('xcrun', 'simctl', 'get_app_container', device, identity, 'app'))
            installed_info = plistlib.loads((installed / 'Info.plist').read_bytes())
            compiled(installed, installed_info)
            require(installed_info['CFBundleIcons'] == app_info['CFBundleIcons'], 'Icon mapping changed on install')
            (OUT / (label + '-launch.txt')).write_text(run('xcrun', 'simctl', 'launch', device, identity) + '\n')
            time.sleep(1)
            run('xcrun', 'simctl', 'terminate', device, identity)
            for appearance in ('light', 'dark'):
                run('xcrun', 'simctl', 'ui', device, 'appearance', appearance)
                time.sleep(1)
                run('xcrun', 'simctl', 'io', device, 'screenshot', OUT / (label + '-' + appearance + '-home.png'))
            run('xcrun', 'simctl', 'uninstall', device, identity)
            results.append({'bundleID': identity, 'registered': True, 'launch': True, 'iconMetadataPreserved': True,
                            'physicalSideStoreOrLiveContainerTest': False})
            (OUT / 'simulator-results.json').write_text(json.dumps(results, indent=2) + '\n')
    finally:
        # Preserve the test's original error even if Simulator cleanup also hangs.
        failed = sys.exc_info()[0] is not None
        cleanup_errors = []
        for action in ('shutdown', 'delete'):
            try:
                run('xcrun', 'simctl', action, device, timeout=30)
            except (RuntimeError, subprocess.TimeoutExpired) as error:
                cleanup_errors.append(str(error))
        (OUT / 'cleanup.json').write_text(json.dumps(cleanup_errors, indent=2) + '\n')
        if cleanup_errors:
            (OUT / 'cleanup-errors.txt').write_text('\n'.join(cleanup_errors) + '\n')
            if not failed:
                raise RuntimeError('Simulator cleanup failed; see cleanup-errors.txt')
    run('git', 'diff', '--exit-code', 'HEAD', '--')
    run('git', 'diff', '--cached', '--exit-code', 'HEAD', '--')
    print('PASS: device asset compilation, independent ImageIO decode, actual Simulator product and two identities.')
    print('SCOPE: screenshots change system UI appearance, not manual tinted/clear icon modes. No physical install, host or IPA test.')


if __name__ == '__main__': main()
