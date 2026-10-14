"""Install the APK under test and require a successful instrumentation report."""
import argparse
from pathlib import Path
import re
import subprocess


def validate(app, tests, output):
    output.mkdir(parents=True, exist_ok=True)
    for apk in (app, tests):
        subprocess.run(["adb", "install", "-r", str(apk)], check=True, timeout=90)
    api = int(subprocess.check_output(["adb", "shell", "getprop", "ro.build.version.sdk"], text=True).strip())
    if api >= 33:
        subprocess.run(["adb", "shell", "pm", "grant", "com.animan.app", "android.permission.POST_NOTIFICATIONS"], check=True, timeout=15)
    result = subprocess.run(["adb", "shell", "am", "instrument", "-w", "-r",
                             "com.animan.app.test/androidx.test.runner.AndroidJUnitRunner"],
                            capture_output=True, text=True, timeout=360)
    report = result.stdout + result.stderr
    (output / "instrumentation.txt").write_text(report)
    logs = subprocess.run(["adb", "logcat", "-d"], capture_output=True, text=True, timeout=30)
    (output / "logcat.txt").write_text(logs.stdout)
    subprocess.run(["adb", "pull", "/sdcard/Android/data/com.animan.app.test/files/screen.png", str(output / "screen.png")], timeout=15)
    print(report)
    if result.returncode or not re.search(r"OK \(1 test\)", report) or "FAILURES" in report or "INSTRUMENTATION_FAILED" in report:
        raise RuntimeError("The installed Android engine did not pass instrumentation")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("app", type=Path)
    parser.add_argument("tests", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    validate(args.app, args.tests, args.output)
