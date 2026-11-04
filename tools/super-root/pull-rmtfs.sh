#!/bin/bash
# Copy this phone's modem file-system partitions (IMEI, RF calibration) from TWRP for
# wland's rmtfs server (/var/local/fw/rmtfs in the iOS root). They are private: they stay
# in backup/ (git-ignored). Phone in TWRP with adb (tools/flame-twrp.sh).
#
#   bash tools/super-root/pull-rmtfs.sh [OUTDIR]      (default backup/rmtfs)
set -euo pipefail
cd "$(dirname "$0")/../.."
out=${1:-backup/rmtfs}
adb get-state 2>/dev/null | grep -q recovery || { echo "phone not in TWRP (adb recovery)" >&2; exit 1; }
mkdir -p "$out"
for p in modemst1 modemst2 fsg fsc; do
	adb exec-out "dd if=/dev/block/by-name/$p bs=65536 2>/dev/null" > "$out/$p.img.part"
	want=$(adb shell "blockdev --getsize64 /dev/block/by-name/$p" | tr -d '\r')
	got=$(stat -c %s "$out/$p.img.part")
	[[ $got == "$want" && $got -gt 0 ]] || { echo "$p: read $got of $want bytes" >&2; exit 1; }
	mv "$out/$p.img.part" "$out/$p.img"
	echo "$p: $got bytes"
done
chmod 600 "$out"/*.img
