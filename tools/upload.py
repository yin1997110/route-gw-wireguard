#!/usr/bin/env python3
"""Upload a local file to PVE host or into an LXC via stdin pipe (no sftp)."""
import base64
import os
import shlex
import sys

import paramiko

HOST = "<PVE_HOST>"
PW = os.environ["PVE_PW"]  # required: export PVE_PW=xxx

local, remote, vmid = sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "-"
data = base64.b64encode(open(local, "rb").read()).decode()

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", password=PW, timeout=20)
cmd = "base64 -d > %s" % shlex.quote(remote)
if vmid != "-":
    cmd = "pct exec %s -- /bin/bash -c %s" % (vmid, shlex.quote(cmd))
i, o, e = c.exec_command(cmd)
i.write(data)
i.channel.shutdown_write()
rc = o.channel.recv_exit_status()
sys.stderr.write(e.read().decode())
c.close()
print("rc=%d uploaded %s -> %s (%d bytes b64)" % (rc, local, remote, len(data)))
sys.exit(rc)
