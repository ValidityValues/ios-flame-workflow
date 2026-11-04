#!/usr/bin/env python3
"""Download and verify everything tools/build-super-root.sh puts into the image.

  fetch.py DOWNLOADS STAGE [--wifi]

DOWNLOADS (kept between runs, resumable): IPSW members, bootstrap, debs, factory parts.
STAGE (recreated): what install-extras.py copies in:
  ipsw/{os,systemos,appos}.dmg   links to the three root images named by BuildManifest
  bootstrap.tar.zst              Procursus rootless bootstrap (with OpenSSH)
  debs/*.deb                     TrollStore Lite + the dependencies the bootstrap lacks
  wifi-fw/*                      (--wifi) radio modem.mdt/bNN + modemr.jsn, vendor
                                 wlanmdsp.mbn, modemuw.jsn, bdwlan-flame*.bin

Everything is pinned: the IPSW by its zip CRCs + Apple's URL, the bootstrap and TrollStore
Lite by SHA-256, the dependencies by the SHA-256 in Procursus' index, the factory image
parts by zip CRCs (same Google archive as tools/ci-full-build.sh).
"""
import hashlib, lzma, os, plistlib, re, shutil, struct, subprocess, sys, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
REMOTEZIP = os.path.join(HERE, '..', 'remotezip.py')

IPSW = ('https://updates.cdn-apple.com/2025FallFCS/fullrestores/122-77006/'
        '1158E502-D76D-4226-AA06-ED5E30CD1111/iPhone10,3,iPhone10,6_16.7.16_20H392_Restore.ipsw')
BOOTSTRAP = ('https://apt.procurs.us/bootstraps/1900/bootstrap-ssh-iphoneos-arm64.tar.zst',
             '2c639b83423e4365a3a849e2bc7c56671cdcc8da534d424b6b1779a27c0c7c08')
PROCURSUS = 'https://apt.procurs.us/'
PROCURSUS_INDEX = PROCURSUS + 'dists/1900/main/binary-iphoneos-arm64/Packages.xz'
TROLLSTORE_LITE = ('https://havoc.app/api/download/package/69cd95cc6779df9c5f279ab6/'
                   'com.opa334.trollstorelite_2.1.1_iphoneos-arm64.deb',
                   '61ffce0715de3043abaf995c303a5975ecae87a406eff9219b15d7d0bba17b33')
FACTORY = 'https://dl.google.com/dl/android/aosp/flame-tp1a.221005.002.b2-factory-38e4f49a.zip'
FACTORY_DIR = 'flame-tp1a.221005.002.b2/'
RADIO = FACTORY_DIR + 'radio-flame-g8150-00123-220708-b-8810441.img'
IMAGE_ZIP = FACTORY_DIR + 'image-flame-tp1a.221005.002.b2.zip'
VENDOR_FW = ['wlanmdsp.mbn', 'modemuw.jsn', 'bdwlan-flame.bin', 'bdwlan-flame-PROTO1.1.bin']
UA = 'Telesphoreo APT-HTTP/1.0.592'


def log(*a):
    print('fetch:', *a, flush=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while b := f.read(1 << 20):
            h.update(b)
    return h.hexdigest()


def download(url, path, digest=None):
    if os.path.exists(path) and (digest is None or sha256(path) == digest):
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Havoc serves debs only to package managers; Procursus refuses that agent
    ua = ['-A', UA] if 'havoc.app' in url else []
    subprocess.run(['curl', '-fsSL', '--retry', '5', '--retry-all-errors', *ua, '-o', path + '.part', url],
                   check=True)
    if digest and sha256(path + '.part') != digest:
        sys.exit(f'fetch: {url}: SHA-256 mismatch (expected {digest})')
    os.replace(path + '.part', path)
    return path


def zip_member(url, name, outdir):
    subprocess.run([sys.executable, REMOTEZIP, url, name, outdir], check=True)
    return os.path.join(outdir, name)


# ---- IPSW: the OS root and its two cryptexes, by BuildManifest ----
def ipsw(dl, stage):
    d = os.path.join(dl, 'ipsw')
    man = zip_member(IPSW, 'BuildManifest.plist', d)
    with open(man, 'rb') as f:
        ident = plistlib.load(f)['BuildIdentities'][0]['Manifest']
    os.makedirs(os.path.join(stage, 'ipsw'))
    for key, link in (('OS', 'os'), ('Cryptex1,SystemOS', 'systemos'), ('Cryptex1,AppOS', 'appos')):
        member = ident[key]['Info']['Path']
        log(f'{key}: {member}')
        path = zip_member(IPSW, member, d)
        os.symlink(os.path.abspath(path), os.path.join(stage, 'ipsw', link + '.dmg'))


# ---- Procursus dependency resolution (Debian control files) ----
def stanzas(text):
    for block in text.split('\n\n'):
        fields, key = {}, None
        for line in block.splitlines():
            if line[:1] in ' \t' and key:
                fields[key] += '\n' + line
            elif ':' in line:
                key, v = line.split(':', 1)
                fields[key] = v.strip()
        if 'Package' in fields:
            yield fields


def depnames(field):
    # "a (>= 1), b | c" -> [[a], [b, c]]; versions are not checked (index = one suite)
    return [[re.sub(r'\s*\(.*\)|:any', '', alt).strip() for alt in grp.split('|')]
            for grp in field.split(',') if grp.strip()]


def debs(dl, stage):
    bs = download(BOOTSTRAP[0], os.path.join(dl, 'jb', 'bootstrap-ssh-iphoneos-arm64.tar.zst'), BOOTSTRAP[1])
    shutil.copy(bs, os.path.join(stage, 'bootstrap.tar.zst'))
    status = subprocess.run(f"zstd -dc '{bs}' | tar -xOf - ./var/jb/Library/dpkg/status", shell=True,
                            check=True, capture_output=True, text=True).stdout
    have = set()
    for s in stanzas(status):
        have.add(s['Package'])
        have.update(n.split()[0] for g in depnames(s.get('Provides', '')) for n in g)
    have.add('firmware')            # virtual packages made by /var/jb/usr/libexec/firmware on the phone
    have.update(('cy+cpu.arm64', 'cy+model.iphone', 'cy+os.ios'))
    idx = download(PROCURSUS_INDEX, os.path.join(dl, 'jb', 'Packages.xz'))
    index = {}
    for s in stanzas(lzma.open(idx, 'rt', errors='replace').read()):
        index[s['Package']] = s          # later stanza = newer version in Procursus' index
    out = os.path.join(stage, 'debs')
    os.makedirs(out)
    tsl = download(TROLLSTORE_LITE[0], os.path.join(dl, 'jb', os.path.basename(TROLLSTORE_LITE[0])),
                   TROLLSTORE_LITE[1])
    shutil.copy(tsl, out)
    want = [g for g in depnames('ldid')]          # TrollStore Lite's Depends
    seen = set()
    while want:
        grp = want.pop()
        if any(n in have or n in seen for n in grp):
            continue
        name = next((n for n in grp if n in index), None)
        if not name:
            sys.exit(f'fetch: no Procursus package for {" | ".join(grp)}')
        seen.add(name)
        s = index[name]
        path = download(PROCURSUS + s['Filename'], os.path.join(dl, 'jb', os.path.basename(s['Filename'])),
                        s['SHA256'])
        shutil.copy(path, out)
        log(f'dep {name} {s["Version"]}')
        want += depnames(s.get('Depends', '')) + depnames(s.get('Pre-Depends', ''))


# ---- Wi-Fi firmware: modem from the radio image (FBPK -> FAT16), rest from vendor.img ----
def fat_files(img, want_dir):
    bps, spc, res, nfat, nroot, ts16, _, spf = struct.unpack_from('<HBHBHHBH', img, 11)
    root = (res + nfat * spf) * bps
    data = root + nroot * 32
    fat = img[res * bps:(res + spf) * bps]

    def entries(raw):
        for i in range(0, len(raw), 32):
            e = raw[i:i + 32]
            if e[0] == 0:
                break
            if e[0] == 0xe5 or e[11] == 0x0f or e[11] & 8:
                continue
            name = e[:8].decode().rstrip() + ('.' + e[8:11].decode().rstrip() if e[8:11].strip() else '')
            yield name.lower(), e[11], struct.unpack_from('<H', e, 26)[0], struct.unpack_from('<I', e, 28)[0]

    def chain(c, size=None):
        out = b''
        while 2 <= c < 0xfff8:
            off = data + (c - 2) * spc * bps
            out += img[off:off + spc * bps]
            c = struct.unpack_from('<H', fat, c * 2)[0]
        return out if size is None else out[:size]

    for name, attr, c, size in entries(img[root:data]):
        if name == want_dir and attr & 0x10:
            for n, a, c2, s2 in entries(chain(c)):
                if not a & 0x10 and n not in ('.', '..'):
                    yield n, chain(c2, s2) if s2 else b''


def wifi(dl, stage):
    fd = os.path.join(dl, 'factory')
    radio = zip_member(FACTORY, RADIO, fd)
    with open(radio, 'rb') as f:
        r = f.read()
    assert r[:4] == b'FBPK', 'radio image is not FBPK'
    o = r.index(b'MSDOS5.0') - 3                # the "modem" entry: a FAT16 volume
    img = r[o:] + bytes(128 << 20)               # the pack drops the volume's zero tail
    out = os.path.join(stage, 'wifi-fw')
    os.makedirs(out)
    n = 0
    for name, body in fat_files(img, 'image'):
        if name.startswith('modem.') or name == 'modemr.jsn':
            with open(os.path.join(out, name), 'wb') as f:
                f.write(body)
            n += 1
    mdt = open(os.path.join(out, 'modem.mdt'), 'rb').read()
    phoff, phn = struct.unpack_from('<I', mdt, 0x1c)[0], struct.unpack_from('<H', mdt, 0x2c)[0]
    for i in range(2, phn):                     # every loadable segment's hash is in the .mdt
        fs = struct.unpack_from('<8I', mdt, phoff + 32 * i)[4]
        if fs:
            seg = open(os.path.join(out, f'modem.b{i:02d}'), 'rb').read()
            assert len(seg) == fs and (hashlib.sha384(seg).digest() in mdt or hashlib.sha256(seg).digest() in mdt), \
                f'modem.b{i:02d} does not match modem.mdt'
    log(f'modem: {n} files from {os.path.basename(radio)}, segment hashes ok')
    image_zip = zip_member(FACTORY, IMAGE_ZIP, fd)
    vendor = os.path.join(fd, 'vendor.img')
    if not os.path.exists(vendor):
        subprocess.run(f"unzip -p '{image_zip}' vendor.img > '{vendor}.part'", shell=True, check=True)
        os.replace(vendor + '.part', vendor)
    debugfs = shutil.which('debugfs') or '/sbin/debugfs'
    for f in VENDOR_FW:
        dst = os.path.join(out, f)
        subprocess.run([debugfs, '-R', f'dump /firmware/{f} {dst}', vendor], check=True, capture_output=True)
        assert os.path.getsize(dst) > 0, f'vendor.img has no /firmware/{f}'
    log('vendor: ' + ' '.join(VENDOR_FW))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(args) != 2:
        sys.exit(__doc__)
    dl, stage = map(os.path.abspath, args)
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    ipsw(dl, stage)
    debs(dl, stage)
    if '--wifi' in sys.argv:
        wifi(dl, stage)
    log('done:', stage)


main()
