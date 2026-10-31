#!/usr/bin/env python3
"""Remote helper for PVE/LXC work (no quoting pain, no sftp surprises).

  python rexec.py run <vmid|-> <script...>      把本地脚本 base64 送进去用 bash 执行
  python rexec.py put <vmid|-> <local> <remote> 把本地文件(可整目录 tar.gz)送进容器
  python rexec.py get <vmid|-> <remote> <local>  从容器取文件回本地
"""
import base64
import io
import os
import shlex
import subprocess
import sys
import tarfile
import tempfile

from ssh_run import connect, run


def b64(blob):
    return base64.b64encode(blob).decode()


def wrapbash(inner):
    return "pct exec %s -- /bin/bash -c %s"


def payload_tar(paths):
    """打包本地文件/目录(整目录递归)为 tar.gz 字节。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for p in paths:
            t.add(p, arcname=os.path.basename(p.rstrip("/\\")))
    return buf.getvalue()


def payload_file(path):
    with open(path, "rb") as f:
        return f.read()


def call(c, vmid, script, tmo=1800):
    cmd = ("pct exec %s -- /bin/bash -c %s" % (vmid, shlex.quote(script))) if vmid != "-" else script
    return run(c, cmd, tmo=tmo)


def put_blob(c, vmid, blob, remote, extract=False):
    """大文件走 sftp → (pct push) → 落地。base64 内联受 Linux 128KB 单参数上限限制，不可靠。"""
    host_tmp = "/tmp/.rexec_%s" % os.path.basename(remote)
    sftp = c.open_sftp()
    try:
        with sftp.open(host_tmp, "wb") as f:
            f.write(blob)
    finally:
        sftp.close()
    ct_tmp = "/tmp/.rexec_%s" % os.path.basename(remote)
    if vmid == "-":
        mv = "mv -f %s %s" % (shlex.quote(host_tmp), shlex.quote(remote))
        script = mv if not extract else _extract_script(remote, ct_tmp, extract)
    else:
        run(c, "pct push %s -- %s %s" % (vmid, shlex.quote(host_tmp), shlex.quote(ct_tmp)))
        run(c, "rm -f %s" % shlex.quote(host_tmp))
        script = _extract_script(remote, ct_tmp, extract)
    return call(c, vmid, script)


def _extract_script(remote, ct_tmp, extract):
    if not extract:
        return "mkdir -p $(dirname %s) && mv -f %s %s && ls -l %s" % (
            shlex.quote(remote), shlex.quote(ct_tmp), shlex.quote(remote), shlex.quote(remote))
    dest = shlex.quote(remote)
    return ("mkdir -p %s && tar xzf %s -C %s --strip-components=1 && rm -f %s && ls -l %s | head -5"
            % (dest, shlex.quote(ct_tmp), dest, shlex.quote(ct_tmp), dest))


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    mode, vmid = sys.argv[1], sys.argv[2]
    c = connect()
    try:
        if mode == "run":
            blob = b"\n".join(open(p, "rb").read() for p in sys.argv[3:])
            rc, out, err = call(c, vmid, "echo %s | base64 -d | /bin/bash -l" % b64(blob))
        elif mode == "put":
            local, remote = sys.argv[3], sys.argv[4]
            is_dir = os.path.isdir(local)
            blob = payload_tar([local]) if is_dir else payload_file(local)
            if len(blob) > 48 * 1024:
                # 目录: remote 就是目标目录(tar 顶层名被 strip)
                rc, out, err = (put_blob(c, vmid, blob, remote.rstrip("/"), extract=True)
                                if is_dir else put_blob(c, vmid, blob, remote))
            else:
                tmp = "/tmp/.rexec_%s" % os.path.basename(remote)
                script = "echo %s | base64 -d > %s" % (b64(blob), tmp)
                if is_dir:
                    # 目录语义统一: remote 即目标目录(tar 顶层名被 strip，contents 直接落地)
                    dest = remote.rstrip("/") or "/"
                    script += "; mkdir -p %s && tar xzf %s -C %s --strip-components=1 && rm -f %s" % (
                        shlex.quote(dest), tmp, shlex.quote(dest), tmp)
                else:
                    script += "; mkdir -p $(dirname %s) && mv -f %s %s && ls -l %s" % (
                        shlex.quote(remote), tmp, shlex.quote(remote), shlex.quote(remote))
                rc, out, err = call(c, vmid, script)
        elif mode == "get":
            remote, local = sys.argv[3], sys.argv[4]
            rc, out, err = call(c, vmid, "base64 -w0 %s" % shlex.quote(remote))
            if rc == 0:
                with open(local, "wb") as f:
                    f.write(base64.b64decode(out))
                print("saved", local, os.path.getsize(local), "bytes")
        else:
            sys.exit(__doc__)
    finally:
        c.close()
    sys.stderr.write(err or "")
    sys.stdout.write(out or "")
    sys.exit(rc)


if __name__ == "__main__":
    main()
