#!/usr/bin/env python3
"""Local TCP forward over the PVE SSH channel.

  python portforward.py --local 18080 --remote <GW_IP>:8080

本机(Windows)无法直连 192.168.1.0/24，浏览器调试统一走这条隧道。
"""
import argparse
import socket
import threading

from ssh_run import connect


def pipe(src, dst):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def serve_one(transport, conn, rhost, rport):
    try:
        ch = transport.open_channel("direct-tcpip", (rhost, rport), conn.getpeername())
    except Exception as e:  # noqa: BLE001
        print("channel failed:", e, flush=True)
        conn.close()
        return
    threading.Thread(target=pipe, args=(conn, ch), daemon=True).start()
    pipe(ch, conn)
    ch.close()
    conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", type=int, default=18080)
    ap.add_argument("--remote", default="<GW_IP>:8080")
    a = ap.parse_args()
    rhost, rport = a.remote.split(":")
    c = connect()
    t = c.get_transport()
    t.set_keepalive(15)
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", a.local))
    srv.listen(32)
    print("forwarding 127.0.0.1:%d -> %s:%s" % (a.local, rhost, rport), flush=True)
    try:
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=serve_one, args=(t, conn, rhost, int(rport)), daemon=True).start()
    finally:
        srv.close()
        c.close()


if __name__ == "__main__":
    main()
