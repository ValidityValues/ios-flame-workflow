#!/usr/bin/env python3
"""Validate ios-flame patch sequencing and source script syntax.

Usage:
  python3 tools/validate-repo.py [--verbose]

Checks:
  1. XNU patch sequence: contiguous numbering, no duplicates, valid patch headers.
  2. Python syntax in tools/ and shim/.
  3. Shell syntax in tools/, shim/, phone/, and xnu/patches/, including nested scripts.
"""
import argparse
import glob
import os
import py_compile
import re
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON_ROOTS = ("tools", "shim")
SHELL_ROOTS = ("tools", "shim", "phone", "xnu/patches")


def green(value):
    return "\033[92m" + value + "\033[0m"


def red(value):
    return "\033[91m" + value + "\033[0m"


def bold(value):
    return "\033[1m" + value + "\033[0m"


def source_files(roots, suffix):
    files = []
    for root in roots:
        pattern = os.path.join(REPO_ROOT, root, "**", "*" + suffix)
        files.extend(glob.glob(pattern, recursive=True))
    return sorted(set(path for path in files if os.path.isfile(path)))


def validate_patches(verbose=False):
    patch_dir = os.path.join(REPO_ROOT, "xnu", "patches")
    patch_files = sorted(glob.glob(os.path.join(patch_dir, "*.patch")))
    if not patch_files:
        print(red("[-] Error: No patch files found in xnu/patches/"))
        return False

    errors = []
    seen_numbers = {}

    for path in patch_files:
        filename = os.path.basename(path)
        match = re.match(r"^(\d{4})-(.+)\.patch$", filename)
        if not match:
            errors.append("Invalid patch filename format: " + filename)
            continue

        number = int(match.group(1))
        if number in seen_numbers:
            errors.append(
                "Duplicate patch number %04d: %s and %s"
                % (number, filename, seen_numbers[number])
            )
        seen_numbers[number] = filename

        if os.path.getsize(path) == 0:
            errors.append("Patch is empty: " + filename)
            continue

        with open(path, "r", errors="ignore") as stream:
            head = stream.read(2048)
        if not ("--- " in head or "diff " in head or "Index:" in head):
            errors.append("Patch missing standard diff header: " + filename)
        if verbose:
            print("    [PATCH] " + filename)

    # These numbers were folded into the preceding patch:
    # 0090 into 0089, 0092-0093 into 0091, and 0101 into 0100.
    folded = {90, 92, 93, 101}
    expected = 1
    for number in sorted(seen_numbers):
        while expected in folded and expected != number:
            expected += 1
        if number != expected:
            errors.append(
                "Gap in patch sequence: expected %04d, found %04d (%s)"
                % (expected, number, seen_numbers[number])
            )
            expected = number + 1
        else:
            expected += 1

    if errors:
        print(red("[-] Patch validation failed with %d error(s):" % len(errors)))
        for error in errors:
            print("    - " + error)
        return False

    print(
        green(
            "[+] Validated %d XNU patches (0001-%04d; folded numbers documented)"
            % (len(patch_files), max(seen_numbers))
        )
    )
    return True


def validate_python_scripts(verbose=False):
    py_files = source_files(PYTHON_ROOTS, ".py")
    if not py_files:
        print(red("[-] Error: No Python source files found in tools/ or shim/"))
        return False

    errors = []
    for path in py_files:
        name = os.path.relpath(path, REPO_ROOT)
        try:
            py_compile.compile(path, doraise=True)
            if verbose:
                print("    [PYTHON] " + name)
        except py_compile.PyCompileError as error:
            errors.append("%s: %s" % (name, error))

    if errors:
        print(red("[-] Python syntax validation failed with %d error(s):" % len(errors)))
        for error in errors:
            print("    - " + error)
        return False

    print(green("[+] Validated %d Python source files" % len(py_files)))
    return True


def validate_shell_scripts(verbose=False):
    sh_files = source_files(SHELL_ROOTS, ".sh")
    sh_files += source_files(SHELL_ROOTS, ".bash")
    sh_files = sorted(set(sh_files))
    if not sh_files:
        print(red("[-] Error: No shell scripts found in project source directories"))
        return False

    errors = []
    for path in sh_files:
        relative = os.path.relpath(path, REPO_ROOT)
        result = subprocess.run(
            ["bash", "-n", path],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            errors.append("%s: %s" % (relative, result.stderr.strip()))
        elif verbose:
            print("    [SHELL] " + relative)

    if errors:
        print(red("[-] Shell syntax validation failed with %d error(s):" % len(errors)))
        for error in errors:
            print("    - " + error)
        return False

    print(green("[+] Validated %d shell scripts (bash -n)" % len(sh_files)))
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Validate ios-flame patch sequencing and source script syntax."
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="show each checked source file",
    )
    args = parser.parse_args()

    print(bold("=== ios-flame repository validation ==="))
    results = (
        validate_patches(args.verbose),
        validate_python_scripts(args.verbose),
        validate_shell_scripts(args.verbose),
    )
    if all(results):
        print(bold(green("\nAll repository checks PASSED.")))
        return 0

    print(bold(red("\nRepository checks FAILED.")))
    return 1


if __name__ == "__main__":
    sys.exit(main())
