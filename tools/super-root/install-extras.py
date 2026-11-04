#!/usr/bin/env python3
"""Finish the super-partition root (run by tools/mkiosroot.sh's hook, as root).

  install-extras.py STAGE MOUNTED_ROOT [--kit DIR] [--rmtfs DIR] [--wlan-conf FILE]
                    [--ssh-key FILE] [--mobile-hash HASH]

STAGE comes from fetch.py. Steps:
  1. tools/sweet-root-tweaks.py (the bring-up changes that reach the home screen)
  2. Procursus rootless bootstrap at /var/jb (a real directory: on this port /var is
     on the same writable volume, no preboot volume to hide it in); its debs (TrollStore
     Lite, ldid, libplist3) waiting in /var/jb/var/cache/sweet/debs
  3. launchd job cache (/System/Library/xpc/launchd.plist, read at boot with
     launchd_unsecure_cache=1): org.iosonpixel.jbinit (first boot: prep_bootstrap, dpkg -i
     the debs, uicache; every boot: register /var/jb apps again if needed), com.openssh.sshd
     (socket-activated on 22 and 2222), and with --kit org.iosonpixel.wland (`wland auto`)
  4. --kit (unpacked full-build artifact, the directory holding phone/): wland, gpu, pmem and
     the debug tools into /var/local/bin, SweetMetal/SweetMetal2 into /System/Library/Extensions
  5. Wi-Fi firmware: STAGE/wifi-fw -> /var/local/fw/modem, --rmtfs -> /var/local/fw/rmtfs
     (modemst1/modemst2/fsg/fsc.img: this phone's IMEI/calibration), --wlan-conf ->
     /var/local/wlan.conf (ssid=/psk=)
Fails if less than 512 MiB stay free for /var.
"""
import glob, os, plistlib, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOBILE = 501
JOBS = '/System/Library/LaunchDaemons/'      # key prefix used for jobs in the launchd cache

JBINIT = r'''#!/var/jb/bin/sh
# org.iosonpixel.jbinit (tools/super-root/install-extras.py): finish the rootless bootstrap
# on the first boot, then install the staged debs and register /var/jb apps.
PATH=/var/jb/usr/bin:/var/jb/bin:/var/jb/usr/sbin:/var/jb/sbin:/usr/bin:/bin:/usr/sbin:/sbin
export PATH
LOG=/var/jb/var/log/sweet-jbinit.log
[ -f $LOG ] && mv -f $LOG $LOG.prev
exec >$LOG 2>&1
echo "jbinit: $(date)"
if [ -f /var/jb/prep_bootstrap.sh ]; then
	echo "jbinit: prep_bootstrap"
	NO_PASSWORD_PROMPT=1 /var/jb/bin/sh /var/jb/prep_bootstrap.sh
fi
D=/var/jb/var/cache/sweet/debs
if ls $D/*.deb >/dev/null 2>&1; then
	echo "jbinit: dpkg -i $(ls $D)"
	dpkg -i $D/*.deb && rm -rf $D
fi
# LaunchServices must be up before uicache can register apps: wait for SpringBoard's
# home screen, retry for ~10 min, again on the next boot until it worked once.
[ -f /var/jb/var/cache/sweet/uicache.done ] && exit 0
n=0
while [ $n -lt 20 ]; do
	sleep 30
	if uicache -a; then
		touch /var/jb/var/cache/sweet/uicache.done
		echo "jbinit: uicache ok"
		exit 0
	fi
	n=$((n + 1))
done
echo "jbinit: uicache failed, retry next boot"
'''


def sh(*cmd, **kw):
    print('+', ' '.join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def install(src, dst, mode, uid=0, gid=0):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)
    os.chown(dst, uid, gid)
    os.chmod(dst, mode)


def mkdirs(path, mode=0o755, uid=0, gid=0):
    os.makedirs(path, exist_ok=True)
    os.chown(path, uid, gid)
    os.chmod(path, mode)


def write(path, data, mode, uid=0, gid=0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb' if isinstance(data, bytes) else 'w') as f:
        f.write(data)
    os.chown(path, uid, gid)
    os.chmod(path, mode)


def opt(name, default=None):
    a = sys.argv
    return a[a.index(name) + 1] if name in a else default


def bootstrap(stage, root):
    priv = os.path.join(root, 'private')
    jb = os.path.join(priv, 'var/jb')
    if os.path.lexists(jb):
        sys.exit(f'install-extras: {jb} already exists')
    sh('sh', '-c', f"zstd -dc '{stage}/bootstrap.tar.zst' | tar --numeric-owner -xpf - -C '{priv}'")
    mh = opt('--mobile-hash')
    if mh:                                    # SHA-512 crypt for mobile (sudo / ssh password)
        mp = os.path.join(jb, 'etc/master.passwd')
        lines = open(mp).read().split('\n')
        lines = [':'.join([f[0], mh] + f[2:]) if f[0] == 'mobile' else l
                 for l, f in ((l, l.split(':')) for l in lines)]
        write(mp, '\n'.join(lines), 0o600)
    key = opt('--ssh-key')
    if key:
        for home, uid in (('var/mobile', MOBILE), ('var/root', 0)):
            d = os.path.join(jb, home, '.ssh')
            mkdirs(d, 0o700, uid, uid)
            install(key, os.path.join(d, 'authorized_keys'), 0o600, uid, uid)
    debs = os.path.join(jb, 'var/cache/sweet/debs')
    mkdirs(os.path.dirname(debs))
    mkdirs(debs)
    for d in glob.glob(os.path.join(stage, 'debs/*.deb')):
        install(d, os.path.join(debs, os.path.basename(d)), 0o644)
    write(os.path.join(jb, 'usr/libexec/sweet-jbinit.sh'), JBINIT, 0o755)
    mkdirs(os.path.join(jb, 'var/log'))
    sshd = plistlib.load(open(os.path.join(jb, 'Library/LaunchDaemons/com.openssh.sshd.plist'), 'rb'))
    return sshd


def kit(kitdir, root):
    jobs = {}
    if not kitdir:
        return jobs
    p = os.path.join(kitdir, 'phone')
    if not os.path.isdir(p):
        sys.exit(f'install-extras: {kitdir} has no phone/ (pass the unpacked artifact\'s release dir)')
    bin_ = os.path.join(root, 'private/var/local/bin')
    mkdirs(os.path.join(root, 'private/var/local'))
    mkdirs(bin_)
    for b in ['wifi/wland', 'gpu/gpu', 'gpu/pmem'] + [os.path.relpath(f, p) for f in glob.glob(p + '/tools/*')]:
        src = os.path.join(p, b)
        if os.path.isfile(src) and not src.endswith(('.plist', '.txt')):
            install(src, os.path.join(bin_, os.path.basename(b)), 0o755)
    for b in ('metal/SweetMetal.bundle', 'metal2/SweetMetal2.bundle'):
        src = os.path.join(p, b)
        if os.path.isdir(src):
            dst = os.path.join(root, 'System/Library/Extensions', os.path.basename(b))
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst)
            sh('chown', '-R', '0:0', dst)
    if os.path.exists(os.path.join(bin_, 'wland')):
        jobs['org.iosonpixel.wland'] = {
            'Label': 'org.iosonpixel.wland',
            'ProgramArguments': ['/var/local/bin/wland', 'auto'],
            'RunAtLoad': True, 'UserName': 'root',
            'EnvironmentVariables': {'PATH': '/var/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'},
        }
    return jobs


def wifi(stage, root):
    fw = os.path.join(root, 'private/var/local/fw')
    mkdirs(os.path.join(root, 'private/var/local'))
    for d in ('', 'modem', 'rmtfs', 'rw'):
        mkdirs(os.path.join(fw, d))
    for f in glob.glob(os.path.join(stage, 'wifi-fw/*')):
        install(f, os.path.join(fw, 'modem', os.path.basename(f)), 0o644)
    r = opt('--rmtfs')
    if r:
        for f in ('modemst1.img', 'modemst2.img', 'fsg.img', 'fsc.img'):
            src = os.path.join(r, f)
            if not os.path.isfile(src):
                sys.exit(f'install-extras: --rmtfs {r} has no {f}')
            install(src, os.path.join(fw, 'rmtfs', f), 0o600)
    c = opt('--wlan-conf')
    if c:
        install(c, os.path.join(root, 'private/var/local/wlan.conf'), 0o600)


def main():
    if len(sys.argv) < 3 or os.geteuid() != 0:
        sys.exit(__doc__)
    stage, root = sys.argv[1], sys.argv[2]
    sh(sys.executable, os.path.join(HERE, '..', 'sweet-root-tweaks.py'), root)
    sshd = bootstrap(stage, root)
    jobs = kit(opt('--kit'), root)
    if os.path.isdir(os.path.join(stage, 'wifi-fw')) or opt('--rmtfs'):
        wifi(stage, root)
    jobs['org.iosonpixel.jbinit'] = {
        'Label': 'org.iosonpixel.jbinit',
        'ProgramArguments': ['/var/jb/bin/sh', '/var/jb/usr/libexec/sweet-jbinit.sh'],
        'RunAtLoad': True, 'UserName': 'root',
    }
    jobs[sshd['Label']] = sshd
    cache = os.path.join(root, 'System/Library/xpc/launchd.plist')
    if not os.path.exists(cache + '.orig'):
        shutil.copy2(cache, cache + '.orig')
    p = plistlib.load(open(cache, 'rb'))
    for label, job in jobs.items():
        p['LaunchDaemons'][JOBS + label + '.plist'] = job
    with open(cache, 'wb') as f:
        plistlib.dump(p, f, fmt=plistlib.FMT_BINARY)
    print('launchd jobs added:', ', '.join(jobs), flush=True)
    st = os.statvfs(root)
    free = st.f_bavail * st.f_frsize >> 20
    print(f'install-extras: {free} MiB free')
    if free < 512:
        sys.exit('install-extras: under 512 MiB free for /var: extend tools/super-root/slim.rules')


main()
