"""Inspect an APK and its Chaquopy archives without changing the application.

Optional LLVM experiments operate on copies and never produce an installable APK.
Sizes are bytes. Nested compressed sizes are part of their parent ZIP's size,
not additional contributions to APK size.
"""
import argparse
from collections import defaultdict
import hashlib
from io import BytesIO
import json
from pathlib import Path
import struct
import subprocess
from zipfile import ZipFile
import zlib


def deflated_size(data, level=9):
    compressor = zlib.compressobj(level, zlib.DEFLATED, -15)
    return len(compressor.compress(data) + compressor.flush())


def elf_sections(data):
    """Read the section table of the ELF64 files shipped in the ARM64 APK."""
    if data[:5] != b"\x7fELF\x02":
        raise ValueError("Expected an ELF64 library")
    endian = "<" if data[5] == 1 else ">"
    header = struct.unpack_from(endian + "HHIQQQIHHHHHH", data, 16)
    offset, stride, count, names_index = header[5], header[10], header[11], header[12]
    table = [struct.unpack_from(endian + "IIQQQQIIQQ", data, offset + n * stride)
             for n in range(count)]
    names_section = table[names_index]
    names = data[names_section[4]:names_section[4] + names_section[5]]
    result = {}
    for section in table:
        name = names[section[0]:].split(b"\0", 1)[0].decode()
        result[name] = {
            "type": section[1], "flags": section[2], "address": section[3],
            "size": section[5], "alignment": section[8],
            "sha256": hashlib.sha256(
                b"" if section[1] == 8 else data[section[4]:section[4] + section[5]]
            ).hexdigest(),
        }
    return result


def analyze(apk, output, strip_tool=None):
    with apk.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    report = {
        "apk": apk.name, "apk_bytes": apk.stat().st_size,
        "sha256": digest,
        "units": "bytes; ZIP payload sizes exclude headers, signing and alignment",
        "compression_experiment": "raw DEFLATE level 9; no rebuilt APK or runtime validation",
    }
    groups = defaultdict(int)
    archives = {}
    native = []
    compression = []
    duplicates = []
    output.mkdir(parents=True, exist_ok=True)
    with ZipFile(apk) as outer:
        for entry in outer.infolist():
            name = entry.filename
            if name.startswith("lib/"):
                group = "native_libraries"
            elif name.startswith("assets/chaquopy/"):
                group = "chaquopy_archives_and_bootstrap"
            elif name.endswith(".dex"):
                group = "android_dex"
            elif name.startswith("res/") or name == "resources.arsc":
                group = "android_resources"
            else:
                group = "other"
            groups[group] += entry.compress_size
            if name.endswith(".so"):
                native.append((name, outer.read(entry), entry.compress_size))
            if name.startswith("lib/") or name.endswith(".dex"):
                compression.append({"name": name, "current": entry.compress_size,
                                    "deflated": deflated_size(outer.read(entry))})
            if not name.endswith(".imy"):
                continue
            packages = defaultdict(int)
            seen = {}
            with ZipFile(BytesIO(outer.read(entry))) as inner:
                for item in inner.infolist():
                    packages[item.filename.split("/")[0]] += item.compress_size
                    data = inner.read(item)
                    if item.filename.endswith(".so"):
                        native.append((name + "!/" + item.filename, data, item.compress_size))
                    if name.endswith("/app.imy") and item.file_size:
                        digest = hashlib.sha256(data).digest()
                        if digest in seen:
                            duplicates.append({"name": item.filename, "same_as": seen[digest],
                                               "compressed_bytes": item.compress_size})
                        else:
                            seen[digest] = item.filename
                archives[name] = {
                    "apk_bytes": entry.compress_size,
                    "packages_compressed_bytes": dict(sorted(packages.items(), key=lambda p: -p[1])),
                    "entries": len(inner.infolist()),
                }
        report["zip_payload_bytes"] = sum(groups.values())
        report["zip_metadata_signing_alignment_bytes"] = apk.stat().st_size - sum(groups.values())
    report["groups"] = dict(groups)
    report["chaquopy_archives"] = archives
    report["duplicate_app_entries"] = duplicates
    report["compression_candidates"] = compression
    report["native_library_count"] = len(native)
    report["installed_storage_bytes"] = None
    report["installed_storage_note"] = (
        "Not derivable from ZIP size. Run Android instrumentation on a fresh test "
        "installation and collect footprint.json after first render. Cache is part of data."
    )
    report["native_sections"] = []
    report["strip_experiments"] = []
    for index, (name, data, compressed) in enumerate(native):
        sections = elf_sections(data)
        debug = sum(s["size"] for n, s in sections.items() if n.startswith((".debug", ".zdebug")))
        symbols = sum(s["size"] for n, s in sections.items() if n in (".symtab", ".strtab"))
        report["native_sections"].append({"name": name, "bytes": len(data),
                                          "compressed_bytes": compressed,
                                          "debug_bytes": debug, "static_symbol_bytes": symbols})
        if not strip_tool or not (debug or symbols):
            continue
        source = output / f"{index}-original.so"
        source.write_bytes(data)
        allocated = {n: s for n, s in sections.items() if s["flags"] & 2}
        for flag in ("--strip-debug", "--strip-unneeded"):
            target = output / f"{index}-{flag.removeprefix('--')}.so"
            subprocess.run([str(strip_tool), flag, str(source), "-o", str(target)], check=True)
            stripped = target.read_bytes()
            after = {n: s for n, s in elf_sections(stripped).items() if s["flags"] & 2}
            if allocated != after:
                raise ValueError(f"Allocated ELF sections changed: {name} ({flag})")
            packed = deflated_size(stripped, 6) if "!/" in name else len(stripped)
            report["strip_experiments"].append({
                "name": name, "flag": flag, "original_bytes": len(data), "stripped_bytes": len(stripped),
                "compression": "DEFLATE level 6" if "!/" in name else "stored",
                "original_recompressed_bytes": deflated_size(data, 6) if "!/" in name else len(data),
                "current_apk_payload_bytes": compressed, "simulated_apk_payload_bytes": packed,
                "deflate_level_9_bytes": deflated_size(stripped) if "!/" in name else None,
                "simulated_apk_saving_bytes": compressed - packed,
                "allocated_sections_unchanged": True,
                "runtime_tested": False,
            })
    target = output / "measurements.json"
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(f"APK: {report['apk_bytes']:,} bytes; {len(native)} native libraries")
    for group, size in groups.items():
        print(f"{group}: {size:,} bytes ({size / report['apk_bytes']:.1%})")
    print(f"Report: {target}")
    for item in report["strip_experiments"]:
        print(f"{item['flag']}: {item['simulated_apk_saving_bytes']:,} bytes saved: {item['name']}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--llvm-strip", type=Path)
    parser.add_argument("--baseline", type=Path, help="Compare with another real APK, not a projection")
    args = parser.parse_args()
    current = analyze(args.apk, args.output, args.llvm_strip)
    if args.baseline:
        baseline = analyze(args.baseline, args.output / "baseline")
        saved = baseline["apk_bytes"] - current["apk_bytes"]
        comparison = {
            "baseline_sha256": baseline["sha256"], "optimized_sha256": current["sha256"],
            "baseline_bytes": baseline["apk_bytes"], "optimized_bytes": current["apk_bytes"],
            "saved_bytes": saved, "saved_percent": round(saved * 100 / baseline["apk_bytes"], 2),
            "group_savings_bytes": {key: baseline["groups"].get(key, 0) - current["groups"].get(key, 0)
                                    for key in baseline["groups"].keys() | current["groups"].keys()},
            "installed_storage_measured": False,
        }
        (args.output / "comparison.json").write_text(json.dumps(comparison, indent=2) + "\n")
        print(f"Measured APK reduction: {saved:,} bytes ({comparison['saved_percent']}%)")
