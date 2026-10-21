"""Run both independent device checks and preserve their combined exit status."""
import argparse
from pathlib import Path
import subprocess
import sys
import json

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('packages', type=Path)
    parser.add_argument('reports', type=Path)
    args = parser.parse_args()
    root, reports = args.packages, args.reports
    script = str(Path(__file__).with_name('android_instrumentation.py'))
    commands = [
        [sys.executable, script, str(root/'AnimeLab-Android-under-test.apk'), str(root/'AnimeLab-instrumentation.apk'), str(reports/'runtime'), '--skip-native-media'],
        [sys.executable, script, str(root/'AnimeLab-native-media-probe.apk'), str(root/'AnimeLab-native-media-tests.apk'), str(reports/'media'), '--package', 'com.animan.nativeprobe'],
    ]
    api = int(subprocess.check_output(['adb', 'shell', 'getprop', 'ro.build.version.sdk'], text=True).strip())
    if api == 29:
        # API 29 x86 guests lack ARM64 translation. Test the exact native
        # storage/media implementations; do not misreport a full-engine run.
        (reports/'runtime').mkdir(parents=True, exist_ok=True)
        (reports/'runtime/skipped.json').write_text(json.dumps({'tested': False,
            'reason': 'Android 10 x86 guest lacks ARM64 translation; storage/media probe runs natively'}))
        commands = commands[1:]
        print('Android 10: native media/storage probe only; full ARM64 runtime needs a phone', flush=True)
    codes = [subprocess.run(command).returncode for command in commands]
    raise SystemExit(1 if any(codes) else 0)
