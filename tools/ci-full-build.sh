#!/bin/bash
# Full CI build for ios-flame. Run on macOS with Xcode and Homebrew dependencies installed.
# Usage: tools/ci-full-build.sh KERNEL_ARTIFACT_DIR BUILD_TREE_ARTIFACT_DIR OUTPUT_DIR
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KERNEL_ARTIFACT="$(cd "$1" && pwd)"
BUILD_TREE_ARTIFACT="$(cd "$2" && pwd)"
OUT="$3"
[[ "$OUT" = /* ]] || OUT="$ROOT/$OUT"
OUT="$(mkdir -p "$OUT" && cd "$OUT" && pwd)"

export PATH="$HOME/.cargo/bin:/opt/homebrew/opt/llvm/bin:/opt/homebrew/opt/bison/bin:/opt/homebrew/opt/flex/bin:$PATH"
mkdir -p "$ROOT/work/dxb" "$ROOT/work/turnip" "$ROOT/work/boot" "$ROOT/downloads/mkbootimg" \
         "$ROOT/downloads/avb" "$ROOT/stock/unpacked" "$ROOT/research/ipsw-x" \
         "$OUT/release/kernel" "$OUT/release/boot" "$OUT/release/phone" \
         "$OUT/release/host" "$OUT/logs"

fail() { echo "ERROR: $*" >&2; exit 1; }
fetch_at_commit() {
    local url="$1" sha="$2" dst="$3"
    mkdir -p "$(dirname "$dst")"
    [[ ! -e "$dst/.git" ]] || rm -rf "$dst"
    git init -q "$dst"
    git -C "$dst" fetch -q --depth 1 "$url" "$sha"
    git -C "$dst" checkout -q --detach FETCH_HEAD
    [[ "$(git -C "$dst" rev-parse HEAD)" = "$sha" ]] || fail "Could not pin $url to $sha"
}

KERNEL="$(find "$KERNEL_ARTIFACT" -maxdepth 1 -type f -name 'kernel.*.sweet' -print -quit)"
[[ -n "$KERNEL" && -s "$KERNEL" ]] || fail "No XNU kernel found in $KERNEL_ARTIFACT"
if [[ -f "$KERNEL_ARTIFACT/SHA256SUMS" ]]; then
    (cd "$KERNEL_ARTIFACT" && shasum -a 256 -c SHA256SUMS)
fi
KERNEL_NAME="$(basename "$KERNEL")"
cp "$KERNEL" "$OUT/release/kernel/$KERNEL_NAME"

BUILD_TREE="$BUILD_TREE_ARTIFACT/buildtree.tgz"
[[ -s "$BUILD_TREE" ]] || fail "xnu-buildtree artifact is missing buildtree.tgz"
tar xzf "$BUILD_TREE" -C "$ROOT/work/dxb"
[[ -s "$ROOT/work/dxb/xnu/bsd/dev/sweet_a6xx.c" ]] || fail "The XNU build tree is missing bsd/dev/sweet_a6xx.c"

# Third-party source revisions are pinned to the versions used by this port.
MESA_SHA=85fda3b36405bcaea8bffc64aa4f2651dc90770d
UNIXNU_SHA=926639cdd43b4372f9369d5d1e0e08122ce4281d
M2V_SHA=720ef1ce9ae2a2068999a8675717418b9416283e
MKBOOTIMG_SHA=d2bb0af5ba6d3198a3e99529c97eda1be0b5a093
AVB_SHA=b27a9aa53d2db7720e4d88d6950dcd979da97de3

fetch_at_commit https://github.com/mesa/mesa.git "$MESA_SHA" "$ROOT/work/turnip/mesa"
fetch_at_commit https://github.com/UniXNU/UniXNU.git "$UNIXNU_SHA" "$ROOT/reference-repos/UniXNU"
fetch_at_commit https://github.com/steelbrain/metal2vulkan.git "$M2V_SHA" "$ROOT/work/metal2vulkan"
fetch_at_commit https://github.com/jbeich/platform_system_tools_mkbootimg.git "$MKBOOTIMG_SHA" "$ROOT/downloads/mkbootimg"
fetch_at_commit https://github.com/AndroidBootloader/platform_external_avb.git "$AVB_SHA" "$ROOT/downloads/avb"

# Apply patches in the same order declared by the pinned UniXNU compiler-input manifest.
MESA="$ROOT/work/turnip/mesa"
UNIXNU="$ROOT/reference-repos/UniXNU"
mesa_patches=(
  patches/mesa/freedreno-tools-nir.patch
  patches/mesa/ir3-darwin-build-id.patch
  patches/mesa/ir3-portable-asm-roundtrip.patch
  patches/mesa/offline-adreno-compiler-probe.patch
  patches/mesa/turnip-darwin-kmd.patch
  patches/mesa/turnip-graphics-cache-feedback.patch
  patches/mesa/turnip-empty-scissor.patch
  patches/mesa/turnip-builtin-shader-pack.patch
  patches/mesa/turnip-host-import-images.patch
)
for patch in "${mesa_patches[@]}"; do
    echo "Applying UniXNU Mesa patch: $patch"
    git -C "$MESA" apply --check "$UNIXNU/$patch"
    git -C "$MESA" apply "$UNIXNU/$patch"
done
git -C "$MESA" apply --check "$ROOT/phone/turnip/patches/0100-sweet-fetch-gmem-min-draws.patch"
git -C "$MESA" apply "$ROOT/phone/turnip/patches/0100-sweet-fetch-gmem-min-draws.patch"

# Build Turnip and the Metal-to-Vulkan bridge for iOS 16.
python3 -m venv "$ROOT/work/turnip/venv"
"$ROOT/work/turnip/venv/bin/python" -m pip install --upgrade pip
"$ROOT/work/turnip/venv/bin/python" -m pip install meson mako pyyaml packaging
tools/build-turnip-ios.sh ios
rustup target add aarch64-apple-ios --toolchain 1.98.0
tools/build-m2v-bridge.sh ios

# Build each component with its existing in-repository build script.
phone/wifi/build.sh
phone/gpu/build.sh
phone/tools/build.sh
phone/metal/build.sh
phone/turnip/build.sh
phone/metal2/build.sh
tools/flamebridge/build.sh

# Extract only the iPhone X device-tree member from Apple's IPSW via HTTP ranges.
# The full IPSW and all resulting proprietary files are kept out of the artifact.
IPSW_URL="https://updates.cdn-apple.com/2025FallFCS/fullrestores/122-77006/1158E502-D76D-4226-AA06-ED5E30CD1111/iPhone10,3,iPhone10,6_16.7.16_20H392_Restore.ipsw"
IPSW_SHA256=ece1194f7e233e9109c5790a8d23a4564a10a254e15ec5b09978a343265568fb
echo "Apple IPSW reference: iOS 16.7.16 (20H392); reference SHA-256 $IPSW_SHA256"
python3 tools/remotezip.py "$IPSW_URL" DeviceTree.d22ap.im4p "$ROOT/research/ipsw-x"
D22AP_IM4P="$(find "$ROOT/research/ipsw-x" -type f -name DeviceTree.d22ap.im4p -print -quit)"
[[ -s "$D22AP_IM4P" ]] || fail "DeviceTree.d22ap.im4p was not extracted from Apple's IPSW"
ipsw img4 im4p extract "$D22AP_IM4P" -o "$ROOT/research/ipsw-x/d22ap.adt"
[[ -s "$ROOT/research/ipsw-x/d22ap.adt" ]] || fail "ipsw did not produce d22ap.adt"
python3 tools/mkadt.py "$ROOT/work/boot/flame-hi.adt" --highmem

# Verify Google's official Pixel 4 factory archive and keep only the stock boot DTB.
FACTORY_URL="https://dl.google.com/dl/android/aosp/flame-tp1a.221005.002.b2-factory-38e4f49a.zip"
FACTORY_SHA256=38e4f49a8f72a8f9522f86874187de47add539372fa8c951d11ebde4f9c21103
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
curl -fL --retry 3 --retry-all-errors --connect-timeout 30 "$FACTORY_URL" -o "$TMP/factory.zip"
printf '%s  %s\n' "$FACTORY_SHA256" "$TMP/factory.zip" | shasum -a 256 -c -

NESTED="$(unzip -Z1 "$TMP/factory.zip" | grep -E '(^|/)image-flame[^/]*\.zip$' | head -n 1 || true)"
if [[ -n "$NESTED" ]]; then
    unzip -p "$TMP/factory.zip" "$NESTED" > "$TMP/image-flame.zip"
    rm -f "$TMP/factory.zip"
    unzip -p "$TMP/image-flame.zip" boot.img > "$ROOT/stock/boot.img"
else
    unzip -p "$TMP/factory.zip" boot.img > "$ROOT/stock/boot.img"
fi
[[ -s "$ROOT/stock/boot.img" ]] || fail "Google factory archive did not contain boot.img"
python3 tools/unpack_bootv2.py "$ROOT/stock/boot.img" "$ROOT/stock/unpacked" > "$OUT/logs/unpack-boot.txt"
[[ -s "$ROOT/stock/unpacked/dtb" ]] || fail "Stock Android boot.img did not contain a DTB"
cp "$ROOT/stock/unpacked/dtb" "$ROOT/stock/dtb"

# The shim loads XNU from the payload; the iOS HFS+ root must already be in userdata.
CMDLINE="debug=0xc serial=3 cpus=8 keepsyms=1 -enable_kprintf_spam -noprogress rd=ufsroot0 ufsrw=1 rootrw=1 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 sweetfb_noconsole=1 sweetfb_hz=60 ufslogsecs=2 flamereboot=300 sweetusb=2 sweetusbframes=0 sweetmtl=2"
python3 tools/mkpayload.py "$KERNEL" "$ROOT/work/boot/flame-hi.adt" "$TMP/payload.bin" --cmdline "$CMDLINE" > "$OUT/logs/mkpayload.txt"
shim/build.sh "$TMP/payload.bin" "$OUT/release/boot/flame-boot.img" > "$OUT/logs/shim-build.txt" 2>&1

# Copy compiled phone components to a predictable layout.
cp "$ROOT/work/boot/flame-hi.adt" "$OUT/release/boot/"
cp -R phone/wifi/out "$OUT/release/phone/wifi"
cp -R phone/gpu/out "$OUT/release/phone/gpu"
cp -R phone/tools/out "$OUT/release/phone/tools"
mkdir -p "$OUT/release/phone/metal" "$OUT/release/phone/metal2"
cp -R phone/metal/out/SweetMetal.bundle "$OUT/release/phone/metal/"
cp -R phone/metal2/out/SweetMetal2.bundle "$OUT/release/phone/metal2/"
cp phone/metal2/out/m2vtest "$OUT/release/phone/metal2/"
cp -R phone/turnip/out "$OUT/release/phone/turnip"
cp -R tools/flamebridge/FlameBridge.app "$OUT/release/host/"
cp tools/flamebridge/ports.txt "$OUT/release/host/"

cat > "$OUT/release/INSTALL.md" <<'EOF'
# ios-flame full build kit

This kit was built by GitHub Actions for Google Pixel 4 (flame), with XNU 8796 and the iOS 16.7.16-era userland target.

## Contents

- boot/flame-boot.img: shim plus XNU payload, packed with the matching stock Pixel 4 DTB and AVB hash footer.
- kernel/: the raw Mach-O XNU kernel used in the boot image.
- boot/flame-hi.adt: generated Apple device tree for this port.
- phone/: compiled Wi-Fi, GPU/memory tools, debug utilities, legacy Metal, Metal 2 and Turnip components.
- host/FlameBridge.app: macOS USB-Ethernet TCP/UDP relay.

## Important before booting

This artifact is not a complete iOS installation. It intentionally does not include Apple's multi-gigabyte iOS root volume, Google's full factory archive, Qualcomm firmware dumps, or private modem/calibration backups. The iOS HFS+ root must already be prepared from the iPhone X iOS 16.7.16 (20H392) IPSW and installed in Pixel 4 userdata using the procedure in the repository README. Without that root volume, XNU cannot reach SpringBoard.

The boot image also does not embed Qualcomm GPU firmware. Metal 2 and Turnip were compiled and are included, but hardware-accelerated graphics requires the matching firmware extracted locally from your official Pixel 4 factory image, then added to the ADT/payload following the repository's tools/mkpayload.py instructions.

## Boot

1. Confirm this is a Pixel 4 (flame) with an unlocked bootloader and keep a stock recovery path available.
2. Back up personal data and per-device partitions before changing userdata.
3. Put the phone in fastboot and verify it appears with fastboot devices.
4. If the iOS root is already installed in userdata, boot the image temporarily:

   ~~~sh
   fastboot boot boot/flame-boot.img
   ~~~

fastboot boot is temporary and does not flash the boot partition. Do not relock the bootloader while using modified software. This project is experimental and disables parts of Apple's normal security model; do not use it with personal data.

## Verify files

From this directory, run:

   ~~~sh
   shasum -a 256 -c SHA256SUMS
   ~~~

All source revisions and build details are in build-info.txt.
EOF

cat > "$OUT/release/build-info.txt" <<EOF
Project: ios-flame-workflow
Repository commit: ${GITHUB_SHA:-local}
Kernel: $KERNEL_NAME
Kernel SHA-256: $(shasum -a 256 "$OUT/release/kernel/$KERNEL_NAME" | awk '{print $1}')
XNU generation: macOS 13.5 / xnu-8796.141.3
Mesa commit: $MESA_SHA
UniXNU patches commit: $UNIXNU_SHA
metal2vulkan commit: $M2V_SHA
mkbootimg commit: $MKBOOTIMG_SHA
avbtools commit: $AVB_SHA
Google stock source: Pixel 4 TP1A.221005.002.B2 factory image, SHA-256 $FACTORY_SHA256
Apple device-tree source: iPhone X iOS 16.7.16 (20H392), IPSW reference SHA-256 $IPSW_SHA256
Build time UTC: $(date -u '+%Y-%m-%dT%H:%M:%SZ')
EOF

(
  cd "$OUT/release"
  find . -type f ! -name SHA256SUMS -print | LC_ALL=C sort | while IFS= read -r file; do
    shasum -a 256 "$file"
  done > SHA256SUMS
)

echo "Full build kit is ready: $OUT/release"
find "$OUT/release" -maxdepth 4 -type f -print | sort
