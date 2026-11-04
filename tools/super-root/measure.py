#!/usr/bin/env python3
"""Size report for the super-partition root: how much of the iOS root survives slim.rules.

  measure.py RULES OS.dmg.list SYSTEMOS.dmg.list APPOS.dmg.list

The .list files are `7zz l IMAGE` listings (7-Zip >= 22 reads the APFS images and
their compressed files' real sizes; nothing is mounted or extracted). Rules use the
rsync subset slim.rules needs: '+'/'-' anchored patterns, first match wins, '*'
within one path component, trailing '/' = directory and everything below it.
"""
import fnmatch, re, sys

LINE = re.compile(r'^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d (\S{5}) +(\d+) +(\d*) +(.*)$')


def rules(path):
    out = []
    for l in open(path):
        l = l.split('#', 1)[0].strip()
        if l:
            sign, pat = l.split(None, 1)
            out.append((sign, pat.rstrip('/').lstrip('/').split('/')))
    return out


def verdict(rs, parts):
    for sign, pat in rs:
        n = len(pat)
        # a directory pattern matches the directory itself and anything below it
        if len(parts) >= n and all(fnmatch.fnmatchcase(a, b) for a, b in zip(parts[:n], pat)):
            return sign
    return '+'


def main():
    rs = rules(sys.argv[1])
    kept = cut = files = 0
    removed = {}
    for lst in sys.argv[2:]:
        for l in open(lst, errors='replace'):
            m = LINE.match(l)
            if not m or m.group(1)[0] == 'D':
                continue
            files += 1
            sz = (int(m.group(2)) + 4095) // 4096 * 4096
            parts = m.group(4).split('/')
            if verdict(rs, parts) == '-':
                cut += sz
                key = '/'.join(parts[:4])
                removed[key] = removed.get(key, 0) + sz
            else:
                kept += sz
    mib = lambda b: b / 2**20
    print(f'files: {files}, full root {mib(kept + cut):.0f} MiB, removed {mib(cut):.0f} MiB, kept {mib(kept):.0f} MiB')
    for k, v in sorted(removed.items(), key=lambda kv: -kv[1])[:25]:
        print(f'  -{mib(v):6.0f} MiB  {k}')
    # HFS+ catalog/attributes/journal for ~320k entries: an estimate, mkiosroot.sh prints df
    meta, jb = 300, 150
    budget = 9296
    free = budget - mib(kept) - meta - jb
    print(f'super image {budget} MiB - files {mib(kept):.0f} - HFS+ metadata ~{meta} - bootstrap+TrollStore ~{jb}'
          f' = ~{free:.0f} MiB free for /var')
    sys.exit(0 if free >= 512 else 1)


main()
