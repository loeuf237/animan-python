"""Run both independent device checks and preserve their combined exit status."""
import argparse
from pathlib import Path
import subprocess
import sys

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('packages', type=Path)
    parser.add_argument('reports', type=Path)
    args = parser.parse_args()
    root, reports = args.packages, args.reports
    script = str(Path(__file__).with_name('android_instrumentation.py'))
    commands = [
        [sys.executable, script, str(root/'Animan-Android-under-test.apk'), str(root/'Animan-instrumentation.apk'), str(reports/'runtime'), '--skip-native-media'],
        [sys.executable, script, str(root/'Animan-native-media-probe.apk'), str(root/'Animan-native-media-tests.apk'), str(reports/'media'), '--package', 'com.animan.nativeprobe'],
    ]
    codes = [subprocess.run(command).returncode for command in commands]
    raise SystemExit(1 if any(codes) else 0)
