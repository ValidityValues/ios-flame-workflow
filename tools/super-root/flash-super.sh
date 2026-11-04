#!/bin/bash
# Write root-super.img (tools/build-super-root.sh) to Pixel 4's super partition from TWRP.
# super holds Android's system/vendor/product: back it up first (default) to get Android
# back later with `adb exec-in 'dd of=/dev/block/by-name/super bs=4194304' < BACKUP`.
#
#   bash tools/super-root/flash-super.sh IMG [--backup FILE | --no-backup]
#                                       (default backup: backup/super-<serial>.img)
#
# XNU's UFS root driver only reads LUN 0: super must be a /dev/block/sdaN partition.
# The image must leave the partition's last 8 MiB for the shim/XNU boot logs.
# Afterwards boot the full-build kit with root_partition=super (boot/cmdline.txt).
set -euo pipefail
cd "$(dirname "$0")/../.."
[[ $# -ge 1 ]] || { sed -n '2,11p' "$0"; exit 2; }
img=$1; shift
backup= nobackup=0
while [[ $# -gt 0 ]]; do
	case $1 in
	--backup) backup=$2; shift 2 ;;
	--no-backup) nobackup=1; shift ;;
	*) echo "unknown option $1" >&2; exit 2 ;;
	esac
done
adb get-state 2>/dev/null | grep -q recovery || { echo "phone not in TWRP (adb recovery)" >&2; exit 1; }
a() { adb shell "$@" | tr -d '\r'; }
dev=$(a readlink -f /dev/block/by-name/super)
[[ $dev =~ ^/dev/block/sda[0-9]+$ ]] || { echo "super is $dev, not on UFS LUN 0 (sda): XNU cannot mount it" >&2; exit 1; }
psize=$(a blockdev --getsize64 "$dev")
isize=$(stat -c %s "$img")
(( isize + 8 * 1048576 <= psize )) || { echo "image $isize B + 8 MiB logs > super $psize B" >&2; exit 1; }
echo "super = $dev, $((psize >> 20)) MiB; image $((isize >> 20)) MiB"

# TWRP maps super's logical partitions (dm-N) and may have them mounted: let go first.
a 'for m in $(grep "^/dev/block/dm-" /proc/mounts | cut -d" " -f2); do umount "$m"; done' || true
if [[ $nobackup == 0 ]]; then
	serial=$(adb get-serialno)
	backup=${backup:-backup/super-$serial.img}
	[[ ! -e $backup ]] || { echo "$backup exists: keep it, pass another --backup or --no-backup" >&2; exit 1; }
	mkdir -p "$(dirname "$backup")"
	echo "backing up super -> $backup"
	adb exec-out "dd if=$dev bs=4194304 2>/dev/null" > "$backup.part"
	[[ $(stat -c %s "$backup.part") == "$psize" ]] || { echo "backup short" >&2; exit 1; }
	mv "$backup.part" "$backup"
fi

echo "writing $img -> $dev"
adb exec-in "dd of=$dev bs=4194304" < "$img"
a sync
sums=$img.gib.sha256
if [[ -f $sums ]]; then
	echo "verifying (SHA-256 per GiB)"
	while read -r i sum len; do
		got=$(a "dd if=$dev bs=1048576 skip=$((i * 1024)) count=$(((len + 1048575) / 1048576)) 2>/dev/null | head -c $len | sha256sum" | cut -d' ' -f1)
		[[ $got == "$sum" ]] || { echo "GiB $i differs" >&2; exit 1; }
		echo "  GiB $i ok"
	done < "$sums"
fi
echo "done: boot the kit built with root_partition=super"
