# XNU for sweet and flame

`patches/` is one series on xnu-8796.141.3 (the iOS 16 generation):

- `0001`-`0081`: ios-sweet (Redmi Note 10 Pro). History in [docs/ios-sweet/NOTES.md](../docs/ios-sweet/NOTES.md).
- `0082`-`0124`: flame (Pixel 4). One line per patch in [NOTES.md](../NOTES.md#flame-patches), the details in
  [HANDOFF.md](../HANDOFF.md). 0090, 0092-0093 and 0101 have no file of their own: they are inside 0089, 0091 and
  0100. 0082 is needed with Xcode 16 or newer (iig emits `IORPC.kernelContent`).

The flame series applies with `git apply` in order on top of the ios-sweet baseline and gives the tree that built
kernel 0124 (checked 2026-10-22).

## Local build (flame)

1. Run [blacktop/darwin-xnu-build](https://github.com/blacktop/darwin-xnu-build) (MIT) once with
   `MACOS_VERSION=13.5`, `MACHINE_CONFIG=SWEET`, `KERNEL_CONFIG=DEVELOPMENT` and these patches in its patch dir
   (the same steps as `.github/workflows/xnu.yml`), checked out at `work/dxb`.
2. After that, `tools/build-xnu.sh /abs/path/build.log` rebuilds incrementally in a few minutes with the installed
   Xcode -> `work/dxb/build/xnu.obj/DEVELOPMENT_ARM64_SWEET/kernel.development.sweet`.
3. A new patch: commit the change in `work/dxb/xnu` (a git repo whose HEAD is baseline + applied patches), then
   `git diff HEAD~1 > xnu/patches/NNNN-flame-NAME.patch`.

## GitHub Actions build

The repository's **Build Pixel 4 XNU** workflow builds the flame patch series on a macOS runner using the pinned blacktop/darwin-xnu-build commit. It targets the XNU 8796 generation (MACOS_VERSION 13.5) with MACHINE_CONFIG SWEET.

Start a build from **Actions → Build Pixel 4 XNU → Run workflow**. Choose DEVELOPMENT, RELEASE, or DEBUG; DEVELOPMENT is the default. The xnu-kernel artifact contains the raw kernel when compilation succeeds, its checksum, build metadata, logs, and available diagnostics. The xnu-buildtree artifact contains generated headers and intermediate files for investigating compile errors.

This workflow produces the raw kernel only. It does not produce a complete boot.img or iOS root image: those steps require the user-supplied stock DTB, AOSP mkbootimg/avbtool, Apple iOS userland files, and other device-specific inputs described in the root README. CI does not flash a phone.
