#!/usr/bin/env python3
"""Non-interactive SSH to PVE host and LXC containers via paramiko.

Usage:
  python ssh_run.py host "<shell cmd>"
  python ssh_run.py ct <vmid> "<shell cmd>"
  python ssh_run.py push <vmid|-> <local_file> <remote_path>   # '-' = PVE host itself
"""
import os
import shlex
import sys
import tempfile

import paramiko

HOST = os.environ.get("PVE_HOST", "<PVE_HOST>")
PW = os.environ["PVE_PW"]  # 必需: export PVE_PW=xxx


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=22, username="root", password=PW,
              timeout=20, banner_timeout=30, auth_timeout=30)
    return c


def run(c, cmd, tmo=600):
    _, o, e = c.exec_command(cmd, timeout=tmo)
    out = o.read().decode(errors="replace")
    err = e.read().decode(errors="replace")
    rc = o.channel.recv_exit_status()
    return rc, out, err


def main():
    mode = sys.argv[1]
    c = connect()
    try:
        if mode == "host":
            rc, out, err = run(c, sys.argv[2])
        elif mode == "ct":
            vmid, inner = sys.argv[2], sys.argv[3]
            cmd = "pct exec %s -- /bin/bash -c %s" % (vmid, shlex.quote(inner))
            rc, out, err = run(c, cmd)
        elif mode == "push":
            vmid, local, remote = sys.argv[2], sys.argv[3], sys.argv[4]
            sftp = c.open_sftp()
            if vmid == "-":
                sftp.put(local, remote)
                rc, out, err = 0, "pushed to host:%s" % remote, ""
            else:
                tmp = "/tmp/.push_%s" % os.path.basename(local)
                sftp.put(local, tmp)
                rc, out, err = run(c, "pct push %s -- %s %s" %
                                   (vmid, shlex.quote(tmp), shlex.quote(remote)))
            sftp.close()
        else:
            sys.exit("bad mode")
    finally:
        c.close()
    sys.stderr.write(err)
    sys.stdout.write(out)
    sys.exit(rc)


if __name__ == "__main__":
    main()
