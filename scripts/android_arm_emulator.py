"""Run the actual ARM64 APK without Android's x86 native-translation layer.

The SDK ships a QEMU ARM backend on Linux. Invoke it directly with software CPU
emulation: the frontend launcher otherwise rejects an ARM guest on an x86 host.
This is a CI test harness, not a component distributed with Animan.
"""
import argparse
import os
from pathlib import Path
import subprocess
import time


def validate(api, app, tests, output, boot_only=False):
    sdk = Path(os.environ['ANDROID_HOME'])
    output.mkdir(parents=True, exist_ok=True)
    backend = sdk / 'emulator/qemu/linux-x86_64/qemu-system-aarch64-headless'
    if not backend.is_file():
        raise RuntimeError('The Android SDK ARM64 emulator backend is missing')
    package = f'system-images;android-{api};google_apis;arm64-v8a'
    avd = f'animan_arm_api_{api}'
    avdmanager = sdk / 'cmdline-tools/latest/bin/avdmanager'
    env = os.environ.copy()
    avd_home = (Path('build/android-ci-avd') / str(api)).resolve()
    avd_home.mkdir(parents=True, exist_ok=True)
    env['ANDROID_AVD_HOME'] = str(avd_home)
    env['ANDROID_EMULATOR_LAUNCHER_DIR'] = str(sdk / 'emulator')
    subprocess.run([str(avdmanager), 'create', 'avd', '--force', '-n', avd, '-k', package], input='no\n', text=True, check=True, timeout=120, env=env)
    # The Linux backend otherwise adds an x86 PCI HDA sound card to the
    # ARM virt machine, which has no PCI bus. Disable guest audio devices too;
    # -noaudio only disables host audio and leaves that incompatible device.
    config = avd_home / (avd + '.avd') / 'config.ini'
    with config.open('a') as settings:
        settings.write('\nhw.audioInput=no\nhw.audioOutput=no\n')
    libraries = [str(sdk / 'emulator/lib64'), str(sdk / 'emulator/lib64/qt/lib')]
    if env.get('LD_LIBRARY_PATH'): libraries.append(env['LD_LIBRARY_PATH'])
    env['LD_LIBRARY_PATH'] = ':'.join(libraries)
    with (output / 'emulator.log').open('w') as log:
        process = subprocess.Popen([str(backend), '-avd', avd, '-accel', 'off', '-memory', '3072', '-cores', '2',
                                    '-no-window', '-gpu', 'swiftshader', '-noaudio', '-no-boot-anim', '-no-snapshot'],
                                   env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 900
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError('ARM64 emulator exited: ' + (output / 'emulator.log').read_text()[-4000:])
                state = subprocess.run(['adb', 'shell', 'getprop', 'sys.boot_completed'], capture_output=True, text=True, timeout=20)
                if state.stdout.strip() == '1': break
                time.sleep(5)
            else: raise RuntimeError('ARM64 emulator did not boot within 15 minutes')
            abi = subprocess.check_output(['adb', 'shell', 'getprop', 'ro.product.cpu.abilist'], text=True, timeout=20).strip()
            print('Native guest ABI:', abi, flush=True)
            if not abi.startswith('arm64-v8a') or 'x86' in abi:
                raise RuntimeError('Test must run on an ARM64 guest without native translation')
            if boot_only:
                print('ARM64 emulator boot probe passed', flush=True)
                return
            for namespace, key in [('global', 'window_animation_scale'), ('global', 'transition_animation_scale'), ('global', 'animator_duration_scale')]:
                subprocess.run(['adb', 'shell', 'settings', 'put', namespace, key, '0'], check=True, timeout=20)
            subprocess.run(['adb', 'shell', 'input', 'keyevent', '82'], check=True, timeout=20)
            from android_instrumentation import validate as instrument
            instrument(app, tests, output)
        finally:
            if process.poll() is None:
                try:
                    with (output / 'logcat.txt').open('w') as logs:
                        subprocess.run(['adb', 'logcat', '-d'], stdout=logs, stderr=subprocess.DEVNULL, timeout=5)
                    subprocess.run(['adb', 'emu', 'kill'], capture_output=True, timeout=5)
                except subprocess.TimeoutExpired: pass
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('api', type=int)
    parser.add_argument('app', type=Path)
    parser.add_argument('tests', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--boot-only', action='store_true')
    args = parser.parse_args()
    validate(args.api, args.app, args.tests, args.output, args.boot_only)
