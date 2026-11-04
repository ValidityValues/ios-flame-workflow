#!/bin/bash
# Build root-super.img on Linux: the iOS 16.7.16 (20H392) root for Pixel 4's super
# partition, slimmed to fit (tools/super-root/slim.rules: ~11.4 -> ~7.2 GiB), with the
# SWEET tweaks, the Procursus rootless bootstrap (/var/jb, OpenSSH), TrollStore Lite
# (installed by dpkg on the first boot), and optionally this repo's Wi-Fi/GPU/Metal kit.
#
#   bash tools/build-super-root.sh [--kit DIR] [--rmtfs DIR] [--wlan-conf FILE] [--ssh-key FILE]
#                             [--no-wifi-fw] [--out IMG]
#
#   --kit DIR        unpacked full-build artifact (the directory with phone/): wland + its
#                    boot job, gpu/pmem/debug tools, SweetMetal(2).bundle
#   --rmtfs DIR      this phone's modemst1.img modemst2.img fsg.img fsc.img (IMEI and RF
#                    calibration; tools/super-root/pull-rmtfs.sh reads them from TWRP).
#                    Default: backup/rmtfs if it exists. Without them the modem does not boot.
#   --wlan-conf FILE ssid=NAME / psk=PASSPHRASE lines: wland joins that network at boot
#   --ssh-key FILE   public key for mobile and root (ssh mobile@phone, sudo for root)
#   --no-wifi-fw     skip the 2.4 GB Google factory image (modem/vendor Wi-Fi firmware)
#   --out IMG        default work/super-root/root-super.img
#   MOBILE_PASSWORD  env: password for mobile (sudo, ssh); asked when unset and on a tty
#
# Needs: Linux, sudo, apfs-fuse, hfsprogs (mkfs.hfsplus, fsck.hfsplus), rsync, zstd, curl,
# python3, unzip, openssl, e2fsprogs (debugfs). Downloads (~10 GB, resumable) go to
# downloads/super-root/. The image holds Apple's iOS, Google's/Qualcomm's firmware and your
# modem data: keep it to yourself (downloads/ and work/ are git-ignored; never upload it).
# Write it with bash tools/super-root/flash-super.sh.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
usage() { sed -n '2,26p' "$0"; exit 2; }

kit= rmtfs= wlan= key= wifi=1 out=work/super-root/root-super.img
[[ -d backup/rmtfs ]] && rmtfs=backup/rmtfs
while [[ $# -gt 0 ]]; do
	case $1 in
	--kit) kit=$(realpath "$2"); shift 2 ;;
	--rmtfs) rmtfs=$2; shift 2 ;;
	--wlan-conf) wlan=$(realpath "$2"); shift 2 ;;
	--ssh-key) key=$(realpath "$2"); shift 2 ;;
	--no-wifi-fw) wifi=0; shift ;;
	--out) out=$2; shift 2 ;;
	*) usage ;;
	esac
done
[[ -z $rmtfs ]] || rmtfs=$(realpath "$rmtfs")
[[ $(uname -s) == Linux ]] || { echo "Linux only (loop-mounted HFS+, apfs-fuse)" >&2; exit 1; }
missing=()
for t in apfs-fuse mkfs.hfsplus fsck.hfsplus rsync zstd curl python3 unzip openssl sudo; do
	command -v $t >/dev/null || missing+=($t)
done
[[ $wifi == 0 ]] || command -v debugfs >/dev/null || [[ -x /sbin/debugfs ]] || missing+=(debugfs)
[[ ${#missing[@]} == 0 ]] || { echo "missing: ${missing[*]}" >&2; exit 1; }
[[ ! -e $out ]] || { echo "$out exists: move it away first" >&2; exit 1; }
mkdir -p "$(dirname "$out")"
out=$(realpath "$out")

hash=
if [[ -z ${MOBILE_PASSWORD+x} && -t 0 ]]; then
	read -rsp "Password for mobile (sudo/ssh; empty = Procursus default 'alpine'): " MOBILE_PASSWORD; echo
fi
[[ -z ${MOBILE_PASSWORD:-} ]] || hash=$(printf '%s' "$MOBILE_PASSWORD" | openssl passwd -6 -stdin)

dl=$ROOT/downloads/super-root
stage=$ROOT/work/super-root/stage
python3 tools/super-root/fetch.py "$dl" "$stage" $([[ $wifi == 1 ]] && echo --wifi)

# The hook runs inside mkiosroot.sh with the new volume mounted read-write.

hook=$stage/hook.sh
trap 'rm -f "$hook"' EXIT
{
	echo '#!/bin/sh'
	printf 'exec sudo python3 %q %q "$1"' "$ROOT/tools/super-root/install-extras.py" "$stage"
	[[ -z $kit ]] || printf ' --kit %q' "$kit"
	[[ -z $rmtfs ]] || printf ' --rmtfs %q' "$rmtfs"
	[[ -z $wlan ]] || printf ' --wlan-conf %q' "$wlan"
	[[ -z $key ]] || printf ' --ssh-key %q' "$key"
	[[ -z $hash ]] || printf ' --mobile-hash %q' "$hash"
	echo
} > "$hook"
chmod 700 "$hook"

MKIOSROOT_FILTER=tools/super-root/slim.rules MKIOSROOT_HOOK=$hook \
	bash tools/mkiosroot.sh "$stage/ipsw/os.dmg" "$stage/ipsw/systemos.dmg" "$stage/ipsw/appos.dmg" "$out" super
rm -f "$hook"

# SHA-256 per GiB: flash-super.sh compares the partition against it after writing.
python3 - "$out" > "$out.gib.sha256" <<'PY'
import hashlib, sys
with open(sys.argv[1], 'rb') as f:
    i = 0
    while b := f.read(1 << 30):
        print(i, hashlib.sha256(b).hexdigest(), len(b)); i += 1
PY
echo "built $out ($(du -h --apparent-size "$out" | cut -f1)); write it: bash tools/super-root/flash-super.sh $out"
[[ -n $rmtfs ]] || echo "note: no --rmtfs: Wi-Fi stays off until /var/local/fw/rmtfs has this phone's images"
