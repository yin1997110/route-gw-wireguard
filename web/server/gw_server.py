#!/usr/bin/env python3
# 职责: 分流网关管理面板的真实后端。部署在 LXC 201 本机，同时托管前端 dist 静态文件，
#       并把 /api/* 映射到真实的 wg / ip / dnsmasq / 矩阵节点池状态。
# 契约: 响应包 {code, data, msg}，与 server/mock-server.js 完全一致(业务错误也回 HTTP 200，
#       由 code 区分)，前端不区分两者。
# 为什么只用标准库: CT201 上没有 node / pip3 / nginx，只有 python3.12 + busybox + iproute2。
#       零依赖 = 二次部署只要 cp 文件 + systemctl start。
# 运行: GW_DIST_DIR=/opt/gw-admin/dist GW_DATA_DIR=/opt/gw-admin/data python3 gw_server.py
# 运维: python3 gw_server.py --status|--sync|--probe N|--switch ID|--apply-rules|--events
#       python3 gw_server.py --set-password <账号> <新密码>
# EXTENSION_POINT: 新接口在 routes_table() 注册，保持与 src/api/*.js 一一对应。
import hashlib
import hmac
import http.cookies
import ipaddress
import json
import os
import re
import secrets
import shlex
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

# ============================================================ 配置常量
# 落点/阈值集中在此，业务代码不出现字面量路径。换机器只改这一段(或用同名环境变量覆盖)。
# EXTENSION_POINT: 新增网关侧文件(如 ipset/nftables)时在此登记路径。
P = {
    "WG_CONF": os.environ.get("GW_WG_CONF", "/etc/wireguard/wg0.conf"),
    "WG_IF": os.environ.get("GW_WG_IF", "wg0"),
    "CHINA_LIST": "/etc/china_ip_list.txt",
    "GFW_CONF": "/etc/dnsmasq.d/99-gfw.conf",
    "DNS_MAIN": os.environ.get("GW_DNS_MAIN_CONF", "/etc/dnsmasq.conf"),
    "CUSTOM_CONF": "/etc/dnsmasq.d/98-custom-domain.conf",
    "PANEL_CONF": "/etc/dnsmasq.d/97-panel.conf",     # 面板接管的下发文件，cron 不覆盖
    "CRON_LISTS": "/etc/cron.d/route-lists",
    "LIST_LOG": "/var/log/update-lists.log",          # cron 更新数据源的落地日志(只读展示)
    "DNS_LEASES": "/var/lib/misc/dnsmasq.leases",     # 有 DHCP 时才有内容，没有就空
    "LOCAL_DNS": "127.0.0.1",                         # 面板测解析时问的"本机分流视图"
    # 查询日志只认 journald：本容器 rsyslog 抢不到 /dev/log，/var/log/syslog 开机即停更
    "DNS_UNIT": os.environ.get("GW_DNS_UNIT", "dnsmasq.service"),
    "UPDATE_LISTS": "/usr/local/bin/update-lists.sh",
    "WG_ROUTE_UP": "/usr/local/bin/wg-route-up.sh",
    "WG_SERVICE": "wg-quick@wg0.service",
}
G = {
    "WG_TABLE": "51820",
    "SPLIT_ALLOWED": "0.0.0.0/1, 128.0.0.0/1",   # 分流固定 AllowedIPs，切换节点时不跟随节点值
    "KEEPALIVE": "25",
    # 下面两个上游/隧道地址是文档占位值：现网用订阅给的真实值，通过 systemd drop-in
    # (GW_GFW_DNS / GW_WG_SRC / GW_MATRIX_URL)覆盖，仓库里不保留可用凭据。
    "GFW_DNS": os.environ.get("GW_GFW_DNS", "198.51.100.53"),   # 走隧道的上游(与 98-custom-domain.conf 一致)
    "DIRECT_DNS": "223.5.5.5",                   # 直连上游(与 dnsmasq.conf server= 一致)
    "WG_SRC": os.environ.get("GW_WG_SRC", "10.14.0.2"),
    "LATENCY_TARGET": "1.1.1.1",                 # 隧道延迟实测目标
    "SWITCH_WAIT": 8,                            # 切换后等待握手秒数
    "PROBE_TIMEOUT": 2.5,
    "PROBE_BATCH": 40,
    "PROBE_EVERY": 5,                            # 后台分批探测节奏(秒)
    "HEALTH_EVERY": 3,                           # 隧道健康检查节奏(秒)
    "PING_EVERY": 15,                            # 实测隧道延迟节奏(秒)
    "SAMPLE_EVERY": 2,                           # 流量采样节奏(秒)
    "MATRIX_FETCH_INTERVAL": 6 * 3600,
    "EVENT_KEEP": 3000,
    "HIT_KEEP": 2000,
    "SERIES_KEEP": 120,
    "LATENCY_KEEP": 150,                         # 隧道延迟历史采样点上限(×PING_EVERY≈37min)
    "JOURNAL_MAX": 400,                          # 日志查看器单次最多取回行数
    "CLIENT_KEEP": 512,                          # 设备观测表最多跟多少个客户端
    "CLIENT_ACTIVE": 180,                        # 最近 N 秒内发过 DNS 查询算"活跃设备"
    "DNS_TEST_TIMEOUT": 4.0,                     # 单次 DNS 探测超时(秒)
    "LOG_UNITS": {                               # 日志查看器白名单：只允许读这些源，杜绝任意 unit 注入
        "dnsmasq": {"label": "DNS 解析(dnsmasq)", "unit": "dnsmasq.service"},
        "wireguard": {"label": "隧道(wg-quick)", "unit": "wg-quick@wg0.service"},
        "panel": {"label": "面板(gw-admin)", "unit": "gw-admin.service"},
        "lists": {"label": "数据源更新日志", "file": P["LIST_LOG"]},
    },
    "FLUSH_EVERY": 15,                           # 高频状态落盘节奏(秒)
    "SESSION_TTL": 7 * 24 * 3600,
    "LOGIN_WINDOW": 600,
    "LOGIN_MAX_FAIL": 8,
}
D = {
    "HOST": os.environ.get("GW_BIND", "0.0.0.0"),
    "PORT": int(os.environ.get("GW_PORT", "8080")),
    "DIST": os.environ.get("GW_DIST_DIR", "/opt/gw-admin/dist"),
    "DATA": os.environ.get("GW_DATA_DIR", "/opt/gw-admin/data"),
    "MATRIX": os.environ.get("GW_MATRIX_URL", "https://matrix.example.com:3333/data.js"),
    "COOKIE": "gw_admin_session",
}
API_VERSION = "1.0"

CTX = threading.local()
LOCK = threading.RLock()
SWITCH_LOCK = threading.Lock()
LAST_SWITCH_ATTEMPT = [0.0]   # 最近一次"动过 wg0.conf"的时刻(含失败回滚)


def log(*a):
    print("[gw-admin]", time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


def ok(data=True, msg="ok"):
    return {"code": 200, "data": data, "msg": msg}


def fail(msg, code=500):
    return {"code": code, "data": None, "msg": msg}


def sh(cmd, timeout=30, shell=False):
    """执行外部命令，永远返回 (rc, stdout, stderr)，不抛异常。"""
    try:
        r = subprocess.run(cmd, shell=shell, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout or "", r.stderr or ""
    except Exception as e:  # noqa: BLE001 - 网关命令失败必须降级，不能让面板崩掉
        return 127, "", str(e)


def read_file(path, default=""):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:  # noqa: BLE001
        return default


# ============================================================ 持久化
class Store:
    """每域一个 JSON 文件。高频状态先进内存(set_mem)，由落盘线程批量写(save_dirty)。"""

    def __init__(self, data_dir):
        self.dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self._mem = {}
        self._dirty = set()

    def path(self, name):
        return os.path.join(self.dir, name)

    def load(self, name, default):
        with LOCK:
            if name in self._mem:
                return self._mem[name]
            try:
                with open(self.path(name), encoding="utf-8") as f:
                    self._mem[name] = json.load(f)
            except Exception:  # noqa: BLE001 - 缺文件/坏文件回落默认值
                self._mem[name] = default
            return self._mem[name]

    def set_mem(self, name, data):
        """只更新内存并标记待落盘(高频写路径)。"""
        with LOCK:
            self._mem[name] = data
            self._dirty.add(name)

    def save(self, name, data):
        with LOCK:
            self._mem[name] = data
            self._dirty.discard(name)
            self._write(name, data)

    def _write(self, name, data):
        tmp = self.path(name + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, self.path(name))
        except Exception as e:  # noqa: BLE001
            log("落盘失败", name, e)

    def save_dirty(self):
        with LOCK:
            names = list(self._dirty)
            for n in names:
                self._dirty.discard(n)
                self._write(n, self._mem.get(n))


S = Store(D["DATA"])

# 网络地址一律由 live_config()/Gateway.lan() 现算，这里只放"探测不到时的空值"，
# 不写死任何 LAN IP/网段（换网络后无需改配置甚至无需重启面板）。
DEFAULT_CONFIG = {
    "wanIf": "", "wanGw": "", "lanIf": "", "lanIp": "", "lanPrefix": 0, "lanCidr": "",
    "dnsAddr": "", "wgLan": "", "mssClamp": True, "listUpdateAt": "04:30",
    "chinaRouteCount": 0, "gfwDomainCount": 0,
    "queryLog": True, "latencyTarget": G["LATENCY_TARGET"], "exitCheckUrl": "https://api.ipify.org",
}
DEFAULT_AUTOSWITCH = {
    "enabled": True, "probeType": "ping", "interval": 30, "timeout": 3,
    "failThreshold": 3, "cooldown": 300, "sameRegionFirst": True, "groups": [], "resetDay": 1,
}


def cfg():
    m = dict(DEFAULT_CONFIG)
    m.update(S.load("config.json", {}))
    return m


def autoswitch():
    m = dict(DEFAULT_AUTOSWITCH)
    m.update(S.load("autoswitch.json", {}))
    return m


# ============================================================ 事件日志
def push_event(etype, message, **extra):
    ev = {"id": int(time.time() * 1000000) % 10**15, "time": int(time.time() * 1000),
          "type": etype, "message": message, "source": extra.pop("source", "面板"),
          "detail": extra.pop("detail", "")}
    ev.update(extra)
    with LOCK:
        try:
            with open(S.path("events.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        except Exception as e:  # noqa: BLE001
            log("事件写入失败", e)
    return ev


def read_events(limit=G["EVENT_KEEP"]):
    with LOCK:
        try:
            with open(S.path("events.jsonl"), encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[-limit:]
        except Exception:  # noqa: BLE001
            return []
    out = []
    for ln in reversed(lines):
        try:
            out.append(json.loads(ln))
        except Exception:  # noqa: BLE001
            continue
    return out


# ============================================================ 网关真实状态
class Gateway:
    def __init__(self):
        self.latency = None
        self.latency_loss = 0.0
        self.measured_at = 0.0      # 最近一次 ping 实测的时刻：判隧道生死只认这个时间之后的数据
        self.exit_ip = None
        self.handshake_age = None
        self._dump_cache = (0.0, {"up": False, "peer": {}})

    def dump(self, force=False, ttl=1.0):
        """wg show <if> dump → 结构化，带 1s 缓存(面板多处读取都复用同一次 fork)。"""
        now = time.time()
        if not force and now - self._dump_cache[0] < ttl:
            return self._dump_cache[1]
        rc, out, _ = sh(["wg", "show", P["WG_IF"], "dump"])
        st = {"up": False, "peer": {}, "listen": "", "fwmark": ""}
        if rc == 0:
            lines = [l.split("\t") for l in out.strip().split("\n") if l.strip()]
            iface = lines[0] if lines else []
            peer = {}
            if len(lines) > 1:
                # 本机 wireguard-tools 的 peer 列序(实测，非文档默认)：
                # 0=pubkey 1=preshared 2=endpoint 3=allowed_ips 4=latest_handshake 5=rx 6=tx 7=keepalive
                # interface 行 0 列是本机私钥，任何情况下都不进接口响应。
                f = lines[1]
                num = lambda i: int(f[i]) if len(f) > i and f[i].isdigit() else 0  # noqa: E731
                peer = {"pubkey": f[0] if f else "", "endpoint": (f[2] if len(f) > 2 else "").strip("()"),
                        "allowed": f[3] if len(f) > 3 else "", "handshake": num(4),
                        "rx": num(5), "tx": num(6), "keepalive": num(7)}
            st = {"up": True, "peer": peer,
                  "listen": iface[2] if len(iface) > 2 else "",
                  "fwmark": iface[3] if len(iface) > 3 else ""}
        self._dump_cache = (now, st)
        return st

    def wan(self):
        _, out, _ = sh(["ip", "-o", "route", "show", "default"])
        for line in out.splitlines():
            p = line.split()
            if "via" in p and "dev" in p:
                return p[p.index("via") + 1], p[p.index("dev") + 1]
        c = cfg()
        return c["wanGw"], c["wanIf"]

    def lan(self):
        """同网段单臂旁路由的 LAN 侧信息：LAN 就是默认路由所在网卡。

        返回 {lanIf, lanIp, lanPrefix, lanCidr, wanIf, wanGw, dnsAddr}。
        全部现取，不依赖 config.json；换 IP/换网段后刷新面板即自动更新。
        """
        gw, iface = self.wan()
        info = {"wanIf": iface, "wanGw": gw, "lanIf": iface, "lanIp": "",
                "lanPrefix": 0, "lanCidr": "", "dnsAddr": ""}
        if not iface:
            return info
        _, out, _ = sh(["ip", "-4", "-o", "addr", "show", "dev", iface, "scope", "global"])
        cands = re.findall(r"inet ([\d.]+)/(\d+)", out or "")
        if not cands:
            return info
        # 多地址时优先选"到上游网关的源地址"，它就是客户端该填的那个地址
        src = ""
        if gw:
            _, route, _ = sh(["ip", "-4", "route", "get", gw])
            m = re.search(r"\bsrc ([\d.]+)", route or "")
            src = m.group(1) if m else ""
        ip, prefix = next(((a, p) for a, p in cands if a == src), cands[0])
        try:
            prefix = int(prefix)
            net = ipaddress.ip_network("%s/%d" % (ip, prefix), strict=False)
        except Exception:  # noqa: BLE001
            return info
        info.update({"lanIp": ip, "lanPrefix": prefix,
                     "lanCidr": str(net), "dnsAddr": ip})
        return info

    def route_count(self):
        _, out, _ = sh(["ip", "-o", "route", "show", "table", "main"])
        return len([l for l in out.splitlines() if l.strip()])

    def table_count(self):
        _, out, _ = sh(["ip", "-o", "route", "show", "table", G["WG_TABLE"]])
        return len([l for l in out.splitlines() if l.strip()])

    def ip_rules(self):
        _, out, _ = sh(["ip", "-o", "rule", "show"])
        return out.strip().splitlines()

    def list_counts(self):
        _, n, _ = sh("wc -l < %s" % P["CHINA_LIST"], shell=True)
        _, d, _ = sh("grep -c '^server=' %s" % P["GFW_CONF"], shell=True)
        # 命令失败时 out 是空串：`(x or 0).strip()` 会拿 int 去 strip()，文件一旦被删就 500
        return int((n or "").strip() or 0), int((d or "").strip() or 0)

    def has_mss_clamp(self):
        # 新方案把钳制放在 ROUTE_GW_MSS 链里，兼容旧版的 FORWARD 直挂规则
        for target in ("ROUTE_GW_MSS", "FORWARD"):
            rc, _, _ = sh(["iptables", "-t", "mangle", "-C", target, "-p", "tcp",
                           "--tcp-flags", "SYN,RST", "SYN", "-j", "TCPMSS", "--clamp-mss-to-pmtu"])
            if rc == 0:
                return True
        return False

    # ---- 写入 ----
    def write_wg_conf(self, pubkey, endpoint):
        """只重写 [Peer] 段；Interface(私钥/FwMark/Table/PostUp/PostDown) 原样保留。"""
        old = read_file(P["WG_CONF"])
        if "[Peer]" not in old:
            return False, "wg0.conf 不可读或缺 [Peer] 段"
        head = old.split("[Peer]")[0]
        new = head + ("[Peer]\nPublicKey = %s\nAllowedIPs = %s\nEndpoint = %s\n"
                      "PersistentKeepalive = %s\n"
                      % (pubkey, G["SPLIT_ALLOWED"], endpoint, G["KEEPALIVE"]))
        tmp = P["WG_CONF"] + ".panel.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(new)
            os.chmod(tmp, 0o600)
            os.replace(tmp, P["WG_CONF"])
        except Exception as e:  # noqa: BLE001
            return False, "写入 wg0.conf 失败: %s" % e
        return True, ""

    def restore_wg_conf(self, text):
        """把整份 wg0.conf 原样写回(切换/回滚失败时用)，只动文件不碰运行中的隧道。"""
        if not text:
            return False
        tmp = P["WG_CONF"] + ".panel.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.chmod(tmp, 0o600)
            os.replace(tmp, P["WG_CONF"])
        except Exception as e:  # noqa: BLE001
            log("还原 wg0.conf 失败", e)
            return False
        return True

    def sync_wg(self):
        """wg syncconf 平滑换 peer：不重建接口、不动策略路由、不断下挂设备。"""
        rc, strip, err = sh(["wg-quick", "strip", P["WG_IF"]])
        if rc != 0:
            return False, "wg-quick strip 失败: " + err.strip()
        try:
            # 本机 wireguard-tools v1.0.20210914 不认 "-"(会当成文件名去 fopen)，
            # 用 /dev/stdin 把 strip 结果喂进去：私钥不落盘，也不依赖版本对短横的支持。
            r = subprocess.run(["wg", "syncconf", P["WG_IF"], "/dev/stdin"], input=strip,
                               capture_output=True, text=True, timeout=20)
            return r.returncode == 0, (r.stderr or "").strip()
        except Exception as e:  # noqa: BLE001
            return False, str(e)

    def anti_loop(self, endpoint_ip):
        gw, wan = self.wan()
        if endpoint_ip and gw:
            sh(["ip", "route", "replace", "%s/32" % endpoint_ip, "via", gw, "dev", wan])

    def conf_peer(self):
        """读 wg0.conf 的 [Peer]，返回 (pubkey, endpoint)；用于和运行中的隧道比对。"""
        conf = read_file(P["WG_CONF"])
        if "[Peer]" not in conf:
            return "", ""
        sec = conf.split("[Peer]", 1)[1]
        pk = re.search(r"PublicKey\s*=\s*(\S+)", sec)
        ep = re.search(r"Endpoint\s*=\s*(\S+)", sec)
        return (pk.group(1) if pk else "", ep.group(1) if ep else "")

    def live_peer(self):
        """运行中隧道的真实 peer，endpoint 去掉 wg dump 的括号。"""
        d = self.dump(force=True).get("peer") or {}
        return d.get("pubkey", ""), (d.get("endpoint") or "").strip("()")

    def wait_handshake(self, timeout=G["SWITCH_WAIT"]):
        deadline = time.time() + timeout
        base = (self.dump(force=True).get("peer") or {}).get("handshake", 0)
        # 换 peer 后同公钥会保留旧会话，空闲隧道不会自己发起握手：
        # 先经隧道打一个包，逼内核对新 endpoint 发起第一次握手，否则这里只会等到超时。
        sh(["ping", "-c", "1", "-W", "1", "-i", "0.2", cfg()["latencyTarget"]], timeout=4)
        while time.time() < deadline:
            now = time.time()
            hs = (self.dump(force=True).get("peer") or {}).get("handshake", 0)
            # 时间戳前进=新 peer 握手成功；没前进但落在本窗口内=刚重建好且已在通信(重启场景)
            if hs and (hs > base or hs >= now - timeout):
                return hs
            time.sleep(0.4)
        return 0

    def reload_dns(self, restart=False):
        # log-queries 只在 dnsmasq 启动时读取，SIGHUP 不生效；只有开关查询日志才需要 restart
        if restart:
            rc, _, err = sh(["systemctl", "restart", "dnsmasq"])
            return rc == 0, err.strip()
        rc, _, err = sh(["systemctl", "reload", "dnsmasq"])
        if rc != 0:
            rc2, _, err2 = sh(["systemctl", "restart", "dnsmasq"])
            return rc2 == 0, (err + err2).strip()
        return True, ""

    def ping_latency(self, target=None):
        """真实隧道延迟：ping 经 wg0 出口，取 avg rtt 与丢包率。"""
        rc, out, _ = sh(["ping", "-c", "4", "-W", "2", target or cfg()["latencyTarget"]], timeout=14)
        m = re.search(r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/", out)
        lm = re.search(r"(\d+)% packet loss", out)
        return (float(m.group(2)) if m else None), (int(lm.group(1)) / 100.0 if lm else 1.0)

    def remeasure(self):
        """实测一次隧道延迟并盖上时间戳：判自愈只看这个时间之后的读数。"""
        self.latency, self.latency_loss = self.ping_latency()
        self.measured_at = time.time()

    def check_exit_ip(self, url):
        # 隧道只承载 IPv4；宿主有 IPv6 时 urllib 可能优先走 IPv6 直连，
        # 拿到的是家里出口而不是隧道出口。优先用 curl -4 强制 IPv4。
        rc, out, _ = sh(["curl", "-4", "-fsS", "--max-time", "6", url], timeout=10)
        if rc == 0 and (out or "").strip():
            return out.strip()[:64]
        try:
            with urllib.request.urlopen(url, timeout=6) as r:
                return r.read().decode(errors="replace").strip()[:64]
        except Exception:  # noqa: BLE001
            return None


GW = Gateway()


def uptime_seconds():
    """隧道运行时长：wg-quick 服务激活时刻距今；取不到则退回容器启动时长。

    用 ActiveEnterTimestamp(可读时间，date -d 转 epoch)，Monotonic 在 LXC 里基准不可靠。
    """
    _, out, _ = sh(["systemctl", "show", P["WG_SERVICE"], "-p", "ActiveEnterTimestamp", "--value"])
    stamp = (out or "").strip()
    _, up, _ = sh("cat /proc/uptime", shell=True)
    mono = int(float(up.split()[0])) if up and up.split() else 0
    if stamp and stamp != "n/a":
        _, epoch, _ = sh("date -d %s +%%s" % shlex.quote(stamp), shell=True)
        if (epoch or "").strip().isdigit():
            return max(0, int(time.time()) - int(epoch.strip()))
    return mono


# ============================================================ 节点池(矩阵页)
def flag_of(cc):
    if not cc or len(cc) != 2:
        return "🌐"
    try:
        return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in cc.upper())
    except Exception:  # noqa: BLE001
        return "🌐"


def node_store():
    return S.load("nodes.json", {"updatedAt": 0, "rows": [], "manual": [],
                                 "excluded": [], "probeCursor": 0, "total": 0})


def save_nodes(ns, flush=False):
    (S.save if flush else S.set_mem)("nodes.json", ns)


def matrix_sync(force=False):
    """拉矩阵页 data.js(window.VPN_DATA) → 面板节点池。
    只导入 WireGuard 节点：本机只有 wireguard-tools，OpenVPN 节点无法真正切换，不给假能力。"""
    ns = node_store()
    if not force and time.time() - ns.get("updatedAt", 0) < G["MATRIX_FETCH_INTERVAL"]:
        return ns
    url = cfg().get("nodeSource") or D["MATRIX"]
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(url, timeout=45, context=ctx) as r:
            raw = r.read().decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        push_event("sub_fail", "矩阵节点源拉取失败，沿用现有节点池", source="节点管理", detail=str(e)[:200])
        return ns
    try:
        data = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        cols = data["meta"]["cols"]      # 缺 meta 的 JSON 会 KeyError，一并算解析失败
    except Exception as e:  # noqa: BLE001
        push_event("sub_fail", "矩阵节点源解析失败", source="节点管理", detail=str(e)[:200])
        return ns
    wgc = (data.get("cfg") or {}).get("wg") or {}
    pubs = wgc.get("pub") or []
    keymap = wgc.get("node") or {}
    excluded = set(ns.get("excluded") or [])
    known = {n["name"]: n for n in ns.get("rows") or []}
    rows = []
    for item in data.get("nodes") or []:
        n = dict(zip(cols, item))
        if n.get("proto") != "wg":
            continue
        kidx = keymap.get(str(n["id"]))
        pubkey = pubs[kidx] if isinstance(kidx, int) and 0 <= kidx < len(pubs) else None
        old = known.get(n["name"]) or {}
        rows.append({
            "id": n["id"], "name": n["name"], "server": n["ip"], "port": n["port"],
            "group": "WG-%s" % (n.get("cc") or "XX"),
            "country": n.get("countryCn") or n.get("cc") or "—",
            "city": (n.get("city") or "—").capitalize(), "cc": n.get("cc"),
            "flag": flag_of(n.get("cc")),
            "status": "offline" if not n.get("alive") else "online",
            "delay": n.get("ping"), "loss": 0, "health": n.get("health"),
            "pubkey": pubkey, "switchable": bool(pubkey), "nodeKeyIndex": kidx,
            "allowedOrigin": n.get("allowed"), "isp": n.get("isp"),
            "proxy": n.get("proxy"), "purity": n.get("purity"), "why": n.get("why"),
            "matrixLastTest": n.get("lastTest"), "upBytes": 0, "downBytes": 0,
            "lastCheck": old.get("lastCheck", 0), "cfail": old.get("cfail", 0),
            "probeHistory": old.get("probeHistory", []),
            "source": "matrix", "excluded": n["name"] in excluded,
        })
    ns.update({"rows": rows, "updatedAt": int(time.time()), "total": len(rows),
               "builtAt": (data.get("meta") or {}).get("builtAt"), "url": url})
    save_nodes(ns, flush=True)
    push_event("sub_fetch", "矩阵节点源同步完成：WireGuard %s 台" % len(rows),
               source="节点管理", detail="数据侧生成时间 builtAt=%s" % ns.get("builtAt"))
    return ns


def all_nodes():
    """池内节点(未隐藏) + 手动节点，并按真实 wg 状态盖上 current。
    注意：一个账号的公钥会在多台同机房节点间复用，所以 current 只按 endpoint(ip:port) 判定。"""
    ns = node_store()
    peer = GW.dump().get("peer") or {}
    cur_ep = peer.get("endpoint", "")
    rows = [dict(n) for n in ns.get("rows") or [] if not n.get("excluded")]
    rows += [dict(n) for n in ns.get("manual") or []]
    for n in rows:
        n["current"] = bool(cur_ep) and cur_ep == "%s:%s" % (n.get("server"), n.get("port"))
    return rows


def find_node(nid):
    try:
        nid = int(nid)
    except Exception:  # noqa: BLE001
        return None, None, node_store()
    ns = node_store()
    for key in ("rows", "manual"):
        for n in ns.get(key) or []:
            if n["id"] == nid:
                return n, key, ns
    return None, None, ns


def current_node():
    return next((n for n in all_nodes() if n.get("current")), None)


PING_RE = re.compile(r"(\d+) received.*?rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)", re.S)


def probe_node(n, wan_if=None):
    """节点入口可达性探测：`ping -I <wan>` 强制从物理出口发，拿到的是"未进隧道"的真实 RTT。
    (WireGuard 端口是 UDP，TCP connect 恒失败，所以不能用 TCP 探活。)"""
    host = n.get("server")
    if not host:
        return False, None, 1.0
    iface = wan_if or GW.wan()[1]
    rc, out, _ = sh(["ping", "-c", "2", "-W", "1", "-i", "0.2", "-I", iface, host], timeout=8)
    m = PING_RE.search(out or "")
    if not m:
        return False, None, 1.0
    return True, round(float(m.group(3)), 1), 0.0 if int(m.group(1)) >= 2 else 0.5


def probe_ids(ids):
    ns = node_store()
    index = {n["id"]: n for n in (ns.get("rows") or []) + (ns.get("manual") or [])}
    ids = [i for i in ids if i in index]
    if not ids:
        return {}
    wan_if = GW.wan()[1]
    out = {}
    with ThreadPoolExecutor(max_workers=min(G["PROBE_BATCH"], len(ids))) as ex:
        futs = {ex.submit(probe_node, index[i], wan_if): i for i in ids}
        for f in futs:
            try:
                out[futs[f]] = f.result()
            except Exception:  # noqa: BLE001
                out[futs[f]] = (False, None, 1.0)
    return out


def apply_probe_results(results):
    """探测结果回写节点池：连续失败达阈值判故障，一次成功即恢复。"""
    ns = node_store()
    thr = autoswitch()["failThreshold"]
    online = fault = 0
    for key in ("rows", "manual"):
        for n in ns.get(key) or []:
            r = results.get(n["id"])
            if not r:
                continue
            good, rtt, loss = r
            hist = (n.get("probeHistory") or [])[-9:] + [1 if good else 0]
            n["probeHistory"] = hist
            n["cfail"] = 0 if good else n.get("cfail", 0) + 1
            n["lastCheck"] = int(time.time() * 1000)
            if good:
                n["delay"] = rtt
                n["loss"] = max(loss, round(1 - hist.count(1) / len(hist), 2))
                if n["status"] != "switching":
                    n["status"] = "online"
                online += 1
            else:
                n["delay"], n["loss"] = None, 1.0
                if n["cfail"] >= thr:
                    if n["status"] != "fault":
                        push_event("node_down", "%s 连续 %s 次 ICMP 探测无回包，判故障" % (n["name"], n["cfail"]),
                                   source="探测", reason="%s:%s 不可达" % (n["server"], n["port"]))
                    n["status"] = "fault"
                    fault += 1
                elif n["status"] == "online" and n["cfail"] >= max(1, thr - 1):
                    n["status"] = "offline"
    save_nodes(ns)
    return online, fault


# ============================================================ 节点切换
def do_switch(nid, kind="manual_switch", reason="用户操作"):
    """真实切换：改写 wg0.conf 的 [Peer] → wg syncconf → 补 anti-loop 路由 → 等握手；
    握手失败自动回滚原配置。AllowedIPs 恒为分流方案固定值，绝不跟随节点的 0.0.0.0/0。"""
    with SWITCH_LOCK:
        node, key, ns = find_node(nid)
        if node is None:
            return fail("节点不存在")
        if not node.get("pubkey"):
            return fail("该节点缺少 WireGuard 公钥(矩阵源未提供)，无法切换")
        prev = current_node()
        if prev and prev["id"] == node["id"]:
            return fail("目标节点已是当前节点")
        old_conf = read_file(P["WG_CONF"])
        endpoint = "%s:%s" % (node["server"], node["port"])
        push_event(kind, "%s切换至 %s %s" % ("手动" if kind == "manual_switch" else "自动",
                                             node.get("flag", ""), node["name"]),
                   source="节点管理", **({"from": prev["name"]} if prev else {}),
                   to=node["name"], reason=reason)
        for coll in ("rows", "manual"):
            for n in ns.get(coll) or []:
                if n["id"] == node["id"]:
                    n["status"], n["delay"] = "switching", None
        save_nodes(ns, flush=True)
        t0 = time.time()
        LAST_SWITCH_ATTEMPT[0] = t0
        written, err = GW.write_wg_conf(node["pubkey"], endpoint)
        if not written:
            push_event("node_down", "切换失败：%s" % err, source="节点管理", to=node["name"])
            return fail(err)
        # syncconf 必须真的吃进去：否则配置文件跑到了隧道前面，
        # 后续任何回滚都只是在还原一个"从未生效"的版本，文件与现实永久分叉。
        synced, serr = GW.sync_wg()
        if not synced:
            GW.restore_wg_conf(old_conf)
            push_event("node_down", "切换失败：wg syncconf 未生效(%s)，已还原 wg0.conf" % serr,
                       source="节点管理", to=node["name"], reason="隧道保持原 peer")
            return fail("wg syncconf 失败：%s" % serr, 502)
        GW.anti_loop(node["server"])
        hs = GW.wait_handshake()
        cost = round(time.time() - t0, 1)
        if not hs:
            rolled, rerr = False, ""
            if GW.restore_wg_conf(old_conf):
                rolled, rerr = GW.sync_wg()
                if rolled and prev:
                    GW.anti_loop(prev["server"])
            if not rolled:
                # 文件回到原样但隧道没跟上：此刻唯一安全的是人工介入，不能再盲写
                push_event("self_heal", "%s 握手超时且回滚 syncconf 失败(%s)，wg0.conf 与隧道不一致，"
                                        "请到「系统设置」执行网关重载或人工核对 wg0" % (node["name"], rerr),
                           source="节点管理", to=node["name"], reason="回滚未生效")
                return fail("%s 握手超时，且回滚未生效，请重载网关" % node["name"], 503)
            # 回滚后重新实测：不重测的话，自愈线程会拿着"坏对端期间"留下的 100% 丢包读数，
            # 在几秒后把刚回滚好的健康节点也一起换掉。
            GW.wait_handshake()
            GW.remeasure()
            n2, k2, ns2 = find_node(node["id"])
            if n2 is not None:
                n2.update({"status": "fault", "delay": None, "cfail": n2.get("cfail", 0) + 1})
                save_nodes(ns2, flush=True)
            push_event("node_down", "%s 握手超时(%ss)，已回滚到 %s" %
                       (node["name"], cost, prev["name"] if prev else "原节点"),
                       source="节点管理", to=node["name"], cost=cost,
                       reason="%ss 内未完成握手，已回滚原 peer" % G["SWITCH_WAIT"])
            return fail("%s 握手超时(%ss)，已回滚" % (node["name"], cost), 502)
        n2, k2, ns2 = find_node(node["id"])
        if n2 is not None:
            n2.update({"status": "online", "cfail": 0, "lastCheck": int(time.time() * 1000)})
            save_nodes(ns2, flush=True)
        GW.remeasure()
        GW.exit_ip = GW.check_exit_ip(cfg()["exitCheckUrl"]) or node["server"]
        push_event("node_up", "%s 握手成功，隧道恢复(耗时 %ss)" % (node["name"], cost),
                   source="节点管理", to=node["name"], cost=cost,
                   latency=GW.latency, loss=GW.latency_loss, reason="握手完成")
        return ok({"id": node["id"], "name": node["name"], "endpoint": endpoint,
                   "cost": cost, "handshake": hs})


# ============================================================ 分流规则 → 真实下发
RULES_KEY = "rules.json"


def rules_db():
    db = S.load(RULES_KEY, {"groups": [{"id": 1, "name": "默认组"}], "rows": [], "seq": 1000})
    if not db.get("groups"):
        db["groups"] = [{"id": 1, "name": "默认组"}]
    return db


def apply_rules():
    """启用规则编译成 dnsmasq 片段 + ip 明细路由并下发。
    domain → 97-panel.conf；ip/cidr → 主表(最长前缀压过隧道 0/1+128/1)。"""
    db = rules_db()
    c = cfg()
    lines = ["# /etc/dnsmasq.d/97-panel.conf —— 管理面板生成，勿手改",
             "# 重新下发：面板「分流规则」保存 或 「系统设置-重载配置」", ""]
    if c.get("queryLog"):
        lines.append("log-queries")
    domain_cnt = 0
    errs = []
    for r in sorted(db["rows"], key=lambda x: x.get("priority", 0)):
        if not r.get("enabled") or r.get("type") != "domain":
            continue
        d = re.sub(r"^\*\.?", "", str(r.get("pattern", "")).strip().lower())
        if not d:
            continue
        if r.get("action") == "proxy":
            lines.append("server=/%s/%s" % (d, G["GFW_DNS"]))
        elif r.get("action") == "direct":
            lines.append("server=/%s/%s" % (d, G["DIRECT_DNS"]))
        else:
            lines.append("address=/%s/" % d)
        domain_cnt += 1
    try:
        tmp = P["PANEL_CONF"] + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, P["PANEL_CONF"])
    except Exception as e:  # noqa: BLE001
        errs.append("写入 97-panel.conf 失败: %s" % e)

    wanted = {}
    for r in sorted(db["rows"], key=lambda x: x.get("priority", 0)):
        if r.get("enabled") and r.get("type") in ("ip", "geoip") and "/" in str(r.get("pattern", "")):
            wanted[str(r["pattern"]).strip()] = r.get("action")
    managed = S.load("ip_rules.json", {})
    for cidr in list(managed):
        if wanted.get(cidr) == managed[cidr]:
            continue
        sh(["ip", "route", "del", cidr])
    gw, wan = GW.wan()
    added = 0
    for cidr, action in wanted.items():
        if managed.get(cidr) == action:
            continue
        if action == "direct":
            rc, _, e = sh(["ip", "route", "replace", cidr, "via", gw, "dev", wan])
        elif action == "proxy":
            rc, _, e = sh(["ip", "route", "replace", cidr, "src", G["WG_SRC"], "dev", P["WG_IF"]])
        else:
            rc, _, e = sh(["ip", "route", "replace", cidr, "blackhole"])
        if rc == 0:
            added += 1
        else:
            errs.append("%s %s: %s" % (action, cidr, e.strip()[:120]))
    S.save("ip_rules.json", wanted)
    # log-queries 是启动期选项：只在你我状态不一致时 restart dnsmasq，其余改动 reload 就够(重启会让全网 DNS 抖一下)
    want_log = bool(c.get("queryLog"))
    restart_dns = S.load("dns_state.json", {}).get("queryLog") != want_log
    reloaded, derr = GW.reload_dns(restart=restart_dns)
    if reloaded:
        S.save("dns_state.json", {"queryLog": want_log, "at": int(time.time() * 1000)})
    if not reloaded:
        errs.append("dnsmasq 重载失败: " + derr[:120])
    for r in db["rows"]:
        r["applied"] = bool(r.get("enabled"))
    S.set_mem(RULES_KEY, db)
    push_event("rule_apply", "规则下发：域名 %s 条 / IP 明细新增 %s 撤销 %s" %
               (domain_cnt, added, len([k for k in managed if wanted.get(k) != managed[k]])),
               source="分流规则", detail="; ".join(errs) if errs else "全部成功")
    return {"domains": domain_cnt, "routesAdded": added, "errors": errs}


# ============================================================ 命中日志(dnsmasq query log)
HITS = deque(maxlen=G["HIT_KEEP"])
HIT_COUNT = {}
DOMAIN_RE_CACHE = {}
# 客户端观测：按来源 IP 累计所有 DNS 查询(不止命中规则的)，供「客户端设备」页使用
CLIENTS = {}


def bump_client(client, name, qtype):
    c = CLIENTS.get(client)
    if c is None:
        if len(CLIENTS) >= G["CLIENT_KEEP"]:
            # 上限是"同时被观测到的客户端数"，LAN 内远达不到；真到了就淘汰最久没说话的
            CLIENTS.pop(min(CLIENTS, key=lambda k: CLIENTS[k]["last"]), None)
        c = CLIENTS[client] = {"client": client, "count": 0, "proxy": 0, "direct": 0, "reject": 0,
                               "types": {}, "domains": [], "first": int(time.time() * 1000), "last": 0}
    c["count"] += 1
    c["last"] = int(time.time() * 1000)
    c["types"][qtype] = c["types"].get(qtype, 0) + 1
    if not c["domains"] or c["domains"][-1] != name:
        c["domains"].append(name)
        del c["domains"][:-8]        # 只留最近 8 个查询名(留头不留尾会把它清空)


def parse_query_line(line):
    if "dnsmasq" not in line:
        return
    # dnsmasq 实测行: "… dnsmasq[50172]: query[A] google.com from 192.168.99.10"
    m = re.search(r"query\[(\w+)\]\s+(\S+)\s+from\s+(\S+)", line)
    if not m:
        return
    qtype, name, client = m.group(1), m.group(2).rstrip("."), m.group(3)
    if "." not in name or "@" in name:
        return
    # 回环来源是本机(面板自己测解析、dnsmasq 自检)，不是局域网设备，别混进设备列表
    if client.startswith("127.") or client in ("::1", "localhost"):
        return
    bump_client(client, name, qtype)
    db = rules_db()
    hit = None
    for r in sorted(db["rows"], key=lambda x: x.get("priority", 0)):
        if r.get("type") != "domain" or not r.get("enabled"):
            continue
        pat = str(r["pattern"]).lower().lstrip("*").lstrip(".")
        low = name.lower()
        if pat and (low == pat or low.endswith("." + pat)):
            hit = r
            break
    if not hit:
        return
    c = CLIENTS.get(client)
    if c is not None:
        key = hit["action"] if hit["action"] in ("proxy", "direct") else "reject"
        c[key] = c.get(key, 0) + 1
    now = int(time.time() * 1000)
    HITS.appendleft({"id": now, "time": now, "client": client, "query": name,
                     "action": hit["action"], "ruleId": hit["id"]})
    HIT_COUNT[hit["id"]] = HIT_COUNT.get(hit["id"], 0) + 1
    for r in db["rows"]:
        if r["id"] == hit["id"]:
            r["hits"] = HIT_COUNT[r["id"]]
            r["lastHit"] = now
    S.set_mem(RULES_KEY, db)


def dnsmasq_tail_loop():
    """跟随 dnsmasq 查询日志统计规则命中(面板重启后不追历史)。

    数据源取 journald 而非 /var/log/syslog：本容器里 rsyslogd 抢不到由 journald 持有的
    /dev/log，/var/log/syslog 自开机起就没再写入，只有 journalctl 能拿到实时查询行。
    """
    while True:
        proc = None
        try:
            proc = subprocess.Popen(["journalctl", "-u", P["DNS_UNIT"], "-f", "-n", "0",
                                     "--no-pager", "-o", "short-iso"],
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    text=True, bufsize=1)
            for line in proc.stdout:
                try:
                    parse_query_line(line)
                except Exception as e:  # noqa: BLE001
                    log("解析日志行失败", e)
        except Exception as e:  # noqa: BLE001
            log("dnsmasq 日志跟随失败", e)
        finally:
            if proc:
                proc.terminate()
        time.sleep(5)


# ============================================================ 观测辅助(DNS/设备/日志/数据源)
# 这一节只做"读"：读文件、读邻居表、发一次 UDP 查询。不改隧道、不改规则，接口失败也不能抛异常。
DNS_QTYPES = {"A": 1, "AAAA": 28}
DNS_RCODE = {0: "NOERROR", 1: "FORMERR", 2: "SERVFAIL", 3: "NXDOMAIN", 4: "NOTIMP", 5: "REFUSED"}
DOMAIN_OK_RE = re.compile(r"^[A-Za-z0-9._\-*]{1,253}$")
NEIGH_STATES = ("REACHABLE", "STALE", "DELAY", "PROBE", "FAILED", "PERMANENT", "INCOMPLETE", "NOARP")


def dns_views():
    """解析对比的三个视图：本机分流结果 / 隧道上游 / 直连上游。"""
    return [{"key": "local", "label": "本机 dnsmasq(分流结果)", "server": P["LOCAL_DNS"]},
            {"key": "proxy", "label": "隧道上游", "server": G["GFW_DNS"]},
            {"key": "direct", "label": "直连上游", "server": G["DIRECT_DNS"]}]


def dns_read_name(msg, off, depth=0):
    """解 DNS 报文里的名字(支持压缩指针)；压缩指针后即为段尾，递归深度封顶防构造报文绕圈。"""
    parts = []
    while off < len(msg):
        ln = msg[off]
        if ln == 0:
            return ".".join(parts), off + 1
        if ln & 0xC0 == 0xC0:
            ptr = ((ln & 0x3F) << 8) | (msg[off + 1] if off + 1 < len(msg) else 0)
            if depth < 4:
                sub, _ = dns_read_name(msg, ptr, depth + 1)
                if sub:
                    parts.append(sub)
            return ".".join(parts), off + 2
        parts.append(msg[off + 1:off + 1 + ln].decode("ascii", "replace"))
        off += 1 + ln
    return ".".join(parts), off


def dns_query(server, name, qtype="A", timeout=None):
    """纯标准库发一次 UDP DNS 查询。
    CT201 上没有 dig，getaddrinfo 又只会走 /etc/resolv.conf，没法"分别问三个上游"，
    所以手搓报文：这是面板里唯一直接对外发 UDP 的观测路径，超时/异常一律降级成结构化结果。"""
    t0 = time.time()
    out = {"server": server, "qtype": qtype, "ok": False, "ips": [], "cname": None,
           "rcode": None, "truncated": False, "ms": None, "error": None}
    try:
        tid = secrets.randbelow(65536)
        pkt = struct.pack(">HHHHHH", tid, 0x0100, 1, 0, 0, 0)
        pkt += b"".join(bytes([len(p)]) + p.encode("ascii", "ignore")
                        for p in name.strip(".").split(".") if p) + b"\x00"
        pkt += struct.pack(">HH", DNS_QTYPES[qtype], 1)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.settimeout(timeout or G["DNS_TEST_TIMEOUT"])
            s.sendto(pkt, (server, 53))
            data, _ = s.recvfrom(4096)
        finally:
            s.close()
    except Exception as e:  # noqa: BLE001 - 上游不可达是观测结论，不是服务端故障
        out["error"] = "%s: %s" % (type(e).__name__, str(e)[:80])
        out["ms"] = round((time.time() - t0) * 1000)
        return out
    out["ms"] = round((time.time() - t0) * 1000)
    if len(data) < 12:
        out["error"] = "响应过短"
        return out
    flags, qdcount, ancount = struct.unpack(">HHH", data[2:8])
    out["rcode"] = DNS_RCODE.get(flags & 0xF, str(flags & 0xF))
    out["truncated"] = bool(flags & 0x0200)
    off = 12
    for _ in range(max(0, qdcount)):                     # 跳过问题段(名字 + 类型 + 类)
        _, off = dns_read_name(data, off)
        off += 4
    for _ in range(min(20, max(0, ancount))):            # 资源记录
        _, off = dns_read_name(data, off)
        if off + 10 > len(data):
            break
        rtype, _, _, rdlen = struct.unpack(">HHIH", data[off:off + 10])
        off += 10
        rdata = data[off:off + rdlen]
        off += rdlen
        if rtype == 1 and len(rdata) == 4:
            out["ips"].append(socket.inet_ntoa(rdata))
        elif rtype == 28 and len(rdata) == 16:
            out["ips"].append(socket.inet_ntop(socket.AF_INET6, rdata))
        elif rtype == 5 and out["cname"] is None:
            out["cname"], _ = dns_read_name(data, off - rdlen)
    out["ok"] = out["rcode"] == "NOERROR"
    return out


def dns_matches(name):
    """这个域名会被哪条启用规则接住(与 parse_query_line 同一套匹配语义，只算不改)。"""
    low = name.lower().rstrip(".")
    hits = []
    for r in sorted(rules_db()["rows"], key=lambda x: x.get("priority", 0)):
        if r.get("type") != "domain" or not r.get("enabled"):
            continue
        pat = str(r["pattern"]).lower().lstrip("*").lstrip(".")
        if pat and (low == pat or low.endswith("." + pat)):
            hits.append({"id": r["id"], "pattern": r["pattern"], "action": r["action"],
                         "priority": r.get("priority", 0)})
    return hits


def file_view(path, label):
    """单个配置/数据文件的观测视图：存在性、行数、大小、修改时间。
    行数只在小文件上算(512MB 的机器不能为了看行数把上百 MB 读进内存)。"""
    exists = os.path.isfile(path)
    size = os.path.getsize(path) if exists else 0
    body = [l.strip() for l in read_file(path).splitlines()
            if l.strip() and not l.strip().startswith("#")] if exists and size <= 2 * 1024 * 1024 else []
    _, mtime, _ = sh(["stat", "-c", "%Y", path], timeout=6) if exists else (1, "", "")
    return {"path": path, "label": label, "exists": exists, "bytes": size,
            "counted": bool(exists and size <= 2 * 1024 * 1024),
            "lines": len(body),
            "serverLines": len([l for l in body if l.startswith("server=/")]),
            "addressLines": len([l for l in body if l.startswith("address=/")]),
            "mtime": int((mtime or "").strip() or 0) * 1000}


def tail_lines(path, n):
    """从文件尾部按字节窗口读 n 行(数据源日志可能几百 MB，不能整文件读进来)。"""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - n * 512))
            data = f.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return []
    return data.splitlines()[-n:]


def journal_ts_ms(text):
    m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", text or "")
    if not m:
        return None
    try:
        return int(time.mktime(time.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S")) * 1000)
    except Exception:  # noqa: BLE001
        return None


def unit_state(unit):
    act = sh(["systemctl", "is-active", unit], timeout=6)[1].strip()
    en = sh(["systemctl", "is-enabled", unit], timeout=6)[1].strip()
    return act.split(";")[0], en.split(";")[0]


def lan_neighbors():
    """LAN 邻居表里的下挂设备：只保留默认路由网卡（单臂旁路由的唯一 LAN 口）。"""
    lan_if = GW.lan().get("lanIf") or ""
    _, out, _ = sh(["ip", "-4", "neigh", "show"])
    rows = {}
    for ln in (out or "").splitlines():
        p = ln.split()
        if not p or "dev" not in p or p[0].count(".") != 3:
            continue
        dev = p[p.index("dev") + 1] if len(p) > p.index("dev") + 1 else ""
        if dev == P["WG_IF"] or (lan_if and dev != lan_if):
            continue
        rows[p[0]] = {"ip": p[0], "dev": dev,
                      "mac": p[p.index("lladdr") + 1] if "lladdr" in p else None,
                      "state": p[-1] if p[-1] in NEIGH_STATES else ""}
    return rows


def dnsmasq_leases():
    """dnsmasq 租约(只有配了 DHCP 才有)：格式 "到期 时间戳 IP MAC 主机名 客户端标识"。"""
    rows = {}
    for ln in read_file(P["DNS_LEASES"]).splitlines():
        p = ln.split()
        if len(p) < 5:
            continue
        rows[p[2]] = {"ip": p[2], "mac": p[3], "hostname": p[4] if p[4] != "*" else None,
                      "expires": int(p[0]) * 1000 if p[0].isdigit() else None}
    return rows


def is_ip(s):
    try:
        socket.inet_pton(socket.AF_INET6 if ":" in s else socket.AF_INET, s)
        return True
    except Exception:  # noqa: BLE001
        return False


def next_cron_at(hhmm):
    """下一次数据源更新的时刻(ms)：cron 只有一行"分 时"，按今天/明天推算。"""
    m = re.match(r"^(\d{1,2}):(\d{2})$", str(hhmm) or "")
    if not m:
        return None
    now = time.localtime()
    due = time.mktime((now.tm_year, now.tm_mon, now.tm_mday,
                       int(m.group(1)), int(m.group(2)), 0, 0, 0, -1))
    return int((due + (86400 if due < time.time() else 0)) * 1000)


SWITCH_TYPES = ("manual_switch", "auto_switch", "node_up", "node_down", "self_heal")
SWITCH_TRIGGERS = {"manual_switch": "手动", "auto_switch": "自动自愈", "self_heal": "自动自愈"}


def switch_result(e):
    """把一条"结果事件"翻译成切换结论：成功 / 失败 / 已回滚。
    只读事件文本里的既有措辞，不改自愈线程写的消息，避免动到切换判定。"""
    if not e:
        return "pending"
    msg = e.get("message") or ""
    if e["type"] == "node_up":
        return "success"
    if e["type"] == "node_down":
        return "rollback" if "回滚" in msg else "fail"
    if e["type"] == "self_heal":
        if "成功" in msg:
            return "success"
        return "rollback" if "回滚" in msg else "fail"
    return "info"


# ============================================================ 采样 / 后台线程
TRAFFIC = {"rate_up": 0.0, "rate_down": 0.0, "total_rx": 0, "total_tx": 0, "series": []}
LATENCY = {"series": []}
CPU_PREV = {}
_seq_ev = 0


def cpu_percent():
    with open("/proc/stat") as f:
        p = f.readline().split()[1:]
    idle, total = int(p[3]) + int(p[4]), sum(int(x) for x in p)
    prev = CPU_PREV.get("v")
    CPU_PREV["v"] = (idle, total)
    if not prev:
        return 0.0
    dt, di = total - prev[1], idle - prev[0]
    return 0.0 if dt <= 0 else (1 - di / dt) * 100


def mem_kb():
    info = {}
    for ln in read_file("/proc/meminfo").splitlines():
        k, _, v = ln.partition(":")
        if v.strip():
            info[k] = int(v.split()[0])
    total = info.get("MemTotal", 0)
    avail = info.get("MemAvailable", 0)
    return total, avail


def day_key():
    return time.strftime("%Y-%m-%d")


def mon_key():
    return time.strftime("%Y-%m")


def traffic_loop():
    st = S.load("traffic.json", {"days": {}, "months": {}, "peak_up": 0, "peak_down": 0})
    st["days"].setdefault(day_key(), {"up": 0, "down": 0})
    st["months"].setdefault(mon_key(), {"up": 0, "down": 0})
    S.set_mem("traffic.json", st)
    prev = (None, None, time.time())
    series = S.load("series.json", [])
    with LOCK:
        TRAFFIC["series"] = series[-G["SERIES_KEEP"]:]
    while True:
        time.sleep(G["SAMPLE_EVERY"])
        peer = GW.dump(force=True, ttl=0).get("peer") or {}
        rx, tx = peer.get("rx", 0), peer.get("tx", 0)
        now = time.time()
        dt = max(0.5, now - prev[2])
        if prev[0] is None or rx < prev[0] or tx < prev[1]:
            dr, ur = 0.0, 0.0            # 跨握手/换节点计数清零，本帧不计速率
        else:
            dr, ur = (rx - prev[0]) / dt, (tx - prev[1]) / dt
        prev = (rx, tx, now)
        with LOCK:
            TRAFFIC.update({"rate_up": ur, "rate_down": dr, "total_rx": rx, "total_tx": tx})
            st = S.load("traffic.json", st)
            day = st["days"].setdefault(day_key(), {"up": 0, "down": 0})
            mon = st["months"].setdefault(mon_key(), {"up": 0, "down": 0})
            day["up"] += ur * dt
            day["down"] += dr * dt
            mon["up"] += ur * dt
            mon["down"] += dr * dt
            st["peak_up"] = max(int(st.get("peak_up", 0)), int(ur))
            st["peak_down"] = max(int(st.get("peak_down", 0)), int(dr))
            for k in sorted(st["days"])[:-40]:
                st["days"].pop(k, None)
            S.set_mem("traffic.json", st)
            series = TRAFFIC["series"]
            series.append({"t": int(now * 1000), "up": int(ur), "down": int(dr)})
            del series[:-G["SERIES_KEEP"]]
            S.set_mem("series.json", list(series))


def sample_latency():
    """把每次隧道实测延迟记进历史环形缓冲：延迟曲线只在"真的 ping 过"的点上出样，
    不拿 2s 采样点插值，否则曲线会把一次 15s 的实测抹平成一条直线。"""
    with LOCK:
        if not LATENCY["series"]:
            LATENCY["series"] = list(S.load("latency.json", []))[-G["LATENCY_KEEP"]:]
        LATENCY["series"].append({"t": int(time.time() * 1000),
                                  "ms": round(GW.latency, 1) if GW.latency is not None else None,
                                  "loss": GW.latency_loss})
        del LATENCY["series"][:-G["LATENCY_KEEP"]]
        S.set_mem("latency.json", list(LATENCY["series"]))


def health_loop():
    last_probe = last_ping = last_heal = 0
    last_exit = 0
    while True:
        time.sleep(G["HEALTH_EVERY"])
        try:
            peer = GW.dump(force=True).get("peer") or {}
            hs = peer.get("handshake", 0)
            GW.handshake_age = int(time.time() - hs) if hs else None
            # 隧道健康以"实测 ping"为准：空闲隧道很久不重新握手是正常的，不能按握手年龄判死
            if time.time() - last_ping >= G["PING_EVERY"]:
                last_ping = time.time()
                GW.remeasure()
                sample_latency()
            if time.time() - last_exit > 600:
                last_exit = time.time()
                ip = GW.check_exit_ip(cfg()["exitCheckUrl"])
                GW.exit_ip = ip or (peer.get("endpoint") or "").split(":")[0] or None
            if time.time() - last_probe >= G["PROBE_EVERY"]:
                last_probe = time.time()
                ns = node_store()
                pool = [n["id"] for n in (ns.get("rows") or []) + (ns.get("manual") or [])
                        if not n.get("excluded")]
                if pool:
                    start = ns.get("probeCursor", 0) % len(pool)
                    batch = [pool[(start + i) % len(pool)] for i in range(min(G["PROBE_BATCH"], len(pool)))]
                    ns["probeCursor"] = start + len(batch)
                    save_nodes(ns)
                    try:
                        apply_probe_results(probe_ids(batch))
                    except Exception as e:  # noqa: BLE001
                        log("探测失败", e)
            if time.time() - last_heal >= max(10, autoswitch().get("interval", 30)):
                last_heal = time.time()
                maybe_auto_switch()
        except Exception as e:  # noqa: BLE001
            log("健康检查异常", e)


def maybe_auto_switch():
    a = autoswitch()
    if not a.get("enabled"):
        return False
    if GW.measured_at < LAST_SWITCH_ATTEMPT[0]:
        # 丢包读数是在上一次动 wg0.conf 之前测的(可能是刚失败的坏对端)，不能用来判现在这条隧道
        return False
    cur = current_node()
    # 判坏只看实测：隧道 ping 全丢，或当前节点被探测判故障
    dead = GW.latency_loss >= 1
    if cur is None:
        # peer 对不上节点池(端点漂移/节点被移出池)：隧道通着就不动，实测全丢才需要另找节点
        if not dead:
            return False
    elif not (dead or cur.get("status") == "fault"):
        return False
    if time.time() - S.load("last_switch.json", {"t": 0})["t"] < a.get("cooldown", 300):
        return False
    ns = node_store()
    pool = [n for n in ns.get("rows") or []
            if n.get("switchable") and not n.get("excluded") and (cur is None or n["id"] != cur["id"])
            and n.get("status") in ("online", "offline")]
    if a.get("groups"):
        pool = [n for n in pool if n.get("group") in a["groups"]]
    if not pool:
        push_event("self_heal", "自愈未执行：没有可用候选节点", source="自动自愈",
                   reason="当前 %s 异常，但池内无在线且带公钥的候选" % (cur["name"] if cur else "peer"))
        S.save("last_switch.json", {"t": time.time()})
        return False
    near = [n for n in pool if cur and n.get("country") == cur.get("country")]
    same = [n for n in near if cur and n.get("city") == cur.get("city")]
    ranked = (same or near or pool) if a.get("sameRegionFirst") else pool
    ranked = sorted(ranked, key=lambda n: n["delay"] if n.get("delay") is not None else 1e9)[:3]
    scope = "同城市优先" if same else ("同国家优先" if (near and a.get("sameRegionFirst")) else "跨区域最优延迟")
    cur_name = cur["name"] if cur else "未知对端(端点漂移/节点已出池)"
    if cur is None:
        why = "%s｜隧道实测丢包 100%%" % cur_name
    else:
        why = cur.get("why") or ("%s 丢包 100%%" % cur_name if dead else "节点被探测判故障")
    S.save("last_switch.json", {"t": time.time()})
    for cand in ranked:
        reason = "%s；触发原因=%s(%s)" % (scope, cand.get("why") or why, cur_name)
        r = do_switch(cand["id"], "auto_switch", reason)
        if r["code"] == 200:
            push_event("self_heal", "自愈成功：%s → %s" % (cur_name, cand["name"]),
                       source="自动自愈", reason=reason, **{"from": cur_name, "to": cand["name"]})
            return True
    push_event("self_heal", "自愈失败：3 个候选均无法握手", source="自动自愈",
               reason="保留 %s，冷却 %ss 后重试" % (cur_name, a.get("cooldown")))
    return False


def flush_loop():
    while True:
        time.sleep(G["FLUSH_EVERY"])
        try:
            S.save_dirty()
        except Exception as e:  # noqa: BLE001
            log("批量落盘失败", e)


def matrix_loop():
    for i in range(60):                   # 首次启动等网络稳定，最多 60s
        if GW.dump().get("up"):
            break
        time.sleep(1)
    while True:
        try:
            matrix_sync()
        except Exception as e:  # noqa: BLE001
            log("矩阵同步异常", e)
        time.sleep(300)


# ============================================================ 账号与会话
ITERATIONS = 120000


def hash_pw(password, salt, iterations=ITERATIONS):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations).hex()


def credentials():
    return S.load("credentials.json", {"users": []})


def ensure_admin(password=None):
    c = credentials()
    if c["users"]:
        return None
    password = password or secrets.token_urlsafe(9)
    salt = secrets.token_hex(16)
    c["users"].append({"username": "admin", "salt": salt, "iterations": ITERATIONS,
                       "hash": hash_pw(password, salt), "createdAt": int(time.time() * 1000)})
    S.save("credentials.json", c)
    p = S.path("INITIAL_PASSWORD.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("admin\n%s\n" % password)
    os.chmod(p, 0o600)
    return password


def verify_user(username, password):
    for u in credentials()["users"]:
        if u["username"] == username:
            return hmac.compare_digest(hash_pw(password, u["salt"], u.get("iterations", ITERATIONS)),
                                       u["hash"])
    return False


SESSIONS = {}


def load_sessions():
    for sid, v in list(S.load("sessions.json", {}).items()):
        if v.get("exp", 0) > time.time():
            SESSIONS[sid] = v


def persist_sessions():
    S.save("sessions.json", {k: v for k, v in SESSIONS.items() if v.get("exp", 0) > time.time()})


def new_session(username, ip):
    sid = secrets.token_urlsafe(32)
    SESSIONS[sid] = {"user": username, "exp": time.time() + G["SESSION_TTL"], "ip": ip}
    persist_sessions()
    return sid


def drop_session(sid):
    SESSIONS.pop(sid, None)
    persist_sessions()


LOGIN_FAIL = {}


def login_limited(ip):
    now = time.time()
    q = LOGIN_FAIL.setdefault(ip, deque(maxlen=64))
    while q and now - q[0] > G["LOGIN_WINDOW"]:
        q.popleft()
    return len(q) >= G["LOGIN_MAX_FAIL"]


# ============================================================ 接口表(与 src/api/*.js 一一对应)
def paginate(rows, q):
    try:
        page = max(1, int(q.get("pageNum", 1)))
        size = max(1, int(q.get("pageSize", 10)))
    except Exception:  # noqa: BLE001
        page, size = 1, 10
    return {"rows": rows[(page - 1) * size:page * size], "total": len(rows)}


def node_view(n):
    out = dict(n)
    peer = GW.dump().get("peer") or {}
    if n.get("current"):
        out["exitIp"] = GW.exit_ip or n.get("server")
        out["upBytes"], out["downBytes"] = int(peer.get("tx", 0)), int(peer.get("rx", 0))
        # 当前节点以隧道实测延迟为准；空闲隧道久不重新握手属正常，不按握手年龄判死
        if out.get("status") != "fault" and GW.latency is not None:
            out["delay"] = round(GW.latency, 1)
            out["loss"] = GW.latency_loss
    for k in ("probeHistory", "nodeKeyIndex", "allowedOrigin", "matrixLastTest"):
        out.pop(k, None)
    return out


def live_config():
    """GET /system/config 的返回：全部现取现读，避免面板与网关实际状态漂移。"""
    c = dict(cfg())
    china, gfw = GW.list_counts()
    c["chinaRouteCount"], c["gfwDomainCount"] = china, gfw
    # LAN 与 WAN 是同一块网卡（单臂旁路由），地址/网段全部现算，不读配置文件
    info = GW.lan()
    c.update(info)
    _, out, _ = sh(["ip", "-o", "-4", "addr", "show", "dev", P["WG_IF"]])
    m = re.search(r"inet ([\d./]+)", out or "")
    if m:
        c["wgLan"] = m.group(1)
    c["mssClamp"] = GW.has_mss_clamp()
    c["listUpdateAt"] = cron_time()
    c.setdefault("nodeSource", D["MATRIX"])
    return c


def cron_time():
    for ln in read_file(P["CRON_LISTS"]).splitlines():
        m = re.match(r"^(\d+)\s+(\d+)\s", ln)
        if m:
            return "%02d:%02d" % (int(m.group(2)), int(m.group(1)))
    return cfg()["listUpdateAt"]


def write_cron(hhmm):
    if not re.match(r"^\d{1,2}:\d{2}$", str(hhmm) or ""):
        return "时间格式应为 HH:MM，cron 未修改"
    h, mi = str(hhmm).split(":")
    if not (0 <= int(h) <= 23 and 0 <= int(mi) <= 59):
        return "时间超出范围，cron 未修改"
    body = ("# /etc/cron.d/route-lists —— 由管理面板维护(见 WEB-DEPLOY.md)\n"
            "%s %s * * * root %s >> /var/log/update-lists.log 2>&1\n"
            % (int(mi), int(h), P["UPDATE_LISTS"]))
    try:
        tmp = P["CRON_LISTS"] + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(body)
        os.chmod(tmp, 0o644)
        os.replace(tmp, P["CRON_LISTS"])
    except Exception as e:  # noqa: BLE001
        return "写入 cron 失败: %s" % e
    return "数据源更新时间已改为 %02d:%02d" % (int(h), int(mi))


def manual_node(body, nid):
    return {"id": nid, "name": body.get("name") or "手动节点",
            "server": body.get("server"), "port": int(body.get("port") or 51820),
            "group": body.get("group") or "手动添加",
            "country": body.get("country") or "—", "city": body.get("city") or "—",
            "cc": body.get("cc"), "flag": body.get("flag") or "🌐",
            "status": "offline", "delay": None, "loss": 0,
            "pubkey": body.get("pubkey") or None, "switchable": bool(body.get("pubkey")),
            "upBytes": 0, "downBytes": 0, "lastCheck": 0, "cfail": 0, "probeHistory": [],
            "source": "manual", "excluded": False}


def next_manual_id(ns):
    ids = [n["id"] for n in (ns.get("rows") or []) + (ns.get("manual") or [])]
    return max(max(ids or [0]) + 1, 900000)


NODE_KEYS = ("id", "name", "server", "port", "group", "country", "city", "flag", "pubkey")


def routes_table():
    R = [["POST", r"^/login$", h_login], ["POST", r"^/logout$", h_logout],
         ["GET", r"^/user/info$", h_user_info]]

    # ---- 仪表盘 ----
    def r_overview(q, b, m):
        cur = current_node()
        if cur is None:
            cur = {"name": "未接入节点", "status": "offline", "country": "—", "city": "—",
                   "group": "—", "flag": "🌐", "delay": None, "loss": 1, "current": False}
        st = S.load("traffic.json", {"days": {}, "months": {}, "peak_up": 0, "peak_down": 0})
        nodes = all_nodes()
        with LOCK:
            series = list(TRAFFIC.get("series") or S.load("series.json", []))
        return ok({"node": dict(node_view(cur), uptime=uptime_seconds(),
                                exitIp=GW.exit_ip or cur.get("server")),
                   "meta": {"todayUp": int(st["days"].get(day_key(), {}).get("up", 0)),
                            "todayDown": int(st["days"].get(day_key(), {}).get("down", 0)),
                            "monthUp": int(st["months"].get(mon_key(), {}).get("up", 0)),
                            "monthDown": int(st["months"].get(mon_key(), {}).get("down", 0)),
                            "peakUp": int(st.get("peak_up", 0)), "peakDown": int(st.get("peak_down", 0)),
                            "nodeCount": len(nodes),
                            "onlineCount": len([n for n in nodes if n.get("status") == "online"]),
                            "groupCount": len({n.get("group") for n in nodes if n.get("group")}),
                            "ruleCount": len(rules_db()["rows"])},
                   "series": series})
    R.append(["GET", r"^/dashboard/overview$", r_overview])

    def r_realtime(q, b, m):
        with LOCK:
            ur, dr = TRAFFIC.get("rate_up", 0), TRAFFIC.get("rate_down", 0)
            series = TRAFFIC["series"]
            series.append({"t": int(time.time() * 1000), "up": int(ur), "down": int(dr)})
            del series[:-G["SERIES_KEEP"]]
        total, avail = mem_kb()
        lat = GW.latency if GW.latency is not None else 0
        return ok({"t": int(time.time() * 1000), "up": int(ur), "down": int(dr),
                   "cpu": int(max(0, min(100, round(cpu_percent())))),
                   "mem": int(round((1 - avail / total) * 100)) if total else 0,
                   "latency": round(lat)})
    R.append(["GET", r"^/dashboard/realtime$", r_realtime])

    # ---- 节点 ----
    def r_node_list(q, b, m):
        rows = all_nodes()
        groups = sorted({n.get("group") for n in rows if n.get("group")})
        if q.get("group"):
            rows = [n for n in rows if n.get("group") == q["group"]]
        if q.get("status"):
            rows = [n for n in rows if n.get("status") == q["status"]]
        if q.get("keyword"):
            # 两边都转小写：只降 kw 会让 "TW_Taiwan_60" 这类带大写的节点名永远搜不到
            kw = str(q["keyword"]).lower()
            rows = [n for n in rows if kw in " ".join(
                str(n.get(k, "")) for k in ("name", "server", "city", "country")).lower()]
        rows.sort(key=lambda n: (not n.get("current"), n["delay"] if n.get("delay") is not None else 1e9))
        return ok(dict(paginate([node_view(n) for n in rows], q), groups=groups,
                       # 矩阵地址由后端说了算：前端常量只剩兜底展示作用
                       nodeSource=cfg().get("nodeSource") or D["MATRIX"]))
    R.append(["GET", r"^/node/list$", r_node_list])

    def r_node_add(q, body, m):
        if not body.get("server"):
            return fail("节点地址不能为空")
        ns = node_store()
        nid = next_manual_id(ns)
        n = manual_node(body, nid)
        ns.setdefault("manual", []).append(n)
        save_nodes(ns, flush=True)
        push_event("sys_op", "新增手动节点 %s(%s:%s)" % (n["name"], n["server"], n["port"]), source="节点管理")
        return ok(node_view(dict(n, current=False)))
    R.append(["POST", r"^/node$", r_node_add])

    def r_node_update(q, body, m):
        n, key, ns = find_node(body.get("id", 0))
        if n is None:
            return fail("节点不存在")
        for k in ("name", "group", "country", "city", "flag", "server", "port", "pubkey"):
            if k in body and body[k] not in (None, ""):
                n[k] = body[k]
        if n.get("pubkey"):
            n["switchable"] = True
        save_nodes(ns, flush=True)
        push_event("sys_op", "更新节点 %s" % n["name"], source="节点管理")
        return ok(node_view(dict(n, current=bool(current_node() and current_node()["id"] == n["id"]))))
    R.append(["PUT", r"^/node$", r_node_update])

    def r_node_del(q, b, m):
        ids = [int(x) for x in m[1].split(",")]
        ns = node_store()
        cur = current_node()
        if cur and cur["id"] in ids:
            return fail("当前使用中的节点不可删除")
        before = len(ns.get("manual") or [])
        ns["manual"] = [n for n in (ns.get("manual") or []) if n["id"] not in ids]
        names = {n["name"] for n in (ns.get("rows") or []) if n["id"] in ids}
        excl = set(ns.get("excluded") or []) | names
        ns["excluded"] = sorted(excl)
        for n in ns.get("rows") or []:
            if n["name"] in names:
                n["excluded"] = True
        save_nodes(ns, flush=True)
        push_event("sys_op", "移除节点 %s 个(手动 %s 个；矩阵节点仅隐藏，下次同步不会重新出现)" %
                   (len(ids), before - len(ns["manual"])), source="节点管理")
        return ok({"count": len(ids)})
    R.append(["DELETE", r"^/node/([\d,]+)$", r_node_del])

    def r_node_switch(q, b, m):
        return do_switch(m[1], "manual_switch", "用户操作")
    R.append(["POST", r"^/node/switch/(\d+)$", r_node_switch])

    def r_node_export(q, b, m):
        return ok([{k: n.get(k) for k in NODE_KEYS} for n in all_nodes()])
    R.append(["GET", r"^/node/export$", r_node_export])

    def r_node_import(q, body, m):
        ns = node_store()
        have = {(n["server"], n.get("port")) for n in (ns.get("rows") or []) + (ns.get("manual") or [])}
        added = skipped = 0
        nid = next_manual_id(ns)
        for row in body.get("rows") or []:
            if not row.get("server") or (row["server"], row.get("port", 51820)) in have:
                skipped += 1
                continue
            nid += 1
            ns.setdefault("manual", []).append(manual_node(row, nid))
            have.add((row["server"], row.get("port", 51820)))
            added += 1
        save_nodes(ns, flush=True)
        push_event("sys_op", "批量导入节点：新增 %s，跳过 %s" % (added, skipped), source="节点管理")
        return ok({"added": added, "skipped": skipped})
    R.append(["POST", r"^/node/import$", r_node_import])

    # ---- 分流规则 ----
    def r_group_list(q, b, m):
        db = rules_db()
        return ok([dict(g, ruleCount=len([r for r in db["rows"] if r.get("groupId") == g["id"]]))
                   for g in db["groups"]])
    R.append(["GET", r"^/rule/group$", r_group_list])

    def r_group_add(q, body, m):
        db = rules_db()
        g = {"id": max([x["id"] for x in db["groups"]] or [0]) + 1, "name": body.get("name") or "新组"}
        db["groups"].append(g)
        S.save(RULES_KEY, db)
        return ok(g)
    R.append(["POST", r"^/rule/group$", r_group_add])

    def r_group_del(q, b, m):
        gid = int(m[1])
        db = rules_db()
        db["groups"] = [g for g in db["groups"] if g["id"] != gid]
        removed = [r for r in db["rows"] if r.get("groupId") == gid]
        db["rows"] = [r for r in db["rows"] if r.get("groupId") != gid]
        S.save(RULES_KEY, db)
        apply_rules()
        push_event("rule_apply", "删除分组及其 %s 条规则并重新下发" % len(removed), source="分流规则")
        return ok({"id": gid})
    R.append(["DELETE", r"^/rule/group/(\d+)$", r_group_del])

    def r_rule_list(q, b, m):
        db = rules_db()
        rows = [r for r in db["rows"] if not q.get("groupId") or r.get("groupId") == int(q["groupId"])]
        return ok(sorted(rows, key=lambda r: r.get("priority", 0)))
    R.append(["GET", r"^/rule/list$", r_rule_list])

    def r_rule_add(q, body, m):
        db = rules_db()
        db["seq"] = db.get("seq", 1000) + 1
        r = {"hits": 0, "lastHit": None, "enabled": True, "applied": False, "remark": "",
             "priority": max([x.get("priority", 0) for x in db["rows"]] or [0]) + 1, "id": db["seq"]}
        r.update({k: v for k, v in (body or {}).items() if k in
                  ("groupId", "type", "pattern", "action", "remark", "enabled")})
        if r.get("id") == body.get("id"):
            r["id"] = db["seq"]
        db["rows"].append(r)
        S.save(RULES_KEY, db)
        res = apply_rules()
        return ok(r) if not res["errors"] else ok(dict(r, applyErrors=res["errors"]))
    R.append(["POST", r"^/rule$", r_rule_add])

    def r_rule_update(q, body, m):
        db = rules_db()
        r = next((x for x in db["rows"] if x["id"] == body.get("id")), None)
        if r is None:
            return fail("规则不存在")
        r.update({k: v for k, v in body.items() if k != "id"})
        S.save(RULES_KEY, db)
        res = apply_rules()
        return ok(dict(r, applyErrors=res["errors"]) if res["errors"] else r)
    R.append(["PUT", r"^/rule$", r_rule_update])

    def r_rule_del(q, b, m):
        ids = [int(x) for x in m[1].split(",")]
        db = rules_db()
        db["rows"] = [r for r in db["rows"] if r["id"] not in ids]
        S.save(RULES_KEY, db)
        apply_rules()
        return ok({"count": len(ids)})
    R.append(["DELETE", r"^/rule/([\d,]+)$", r_rule_del])

    def r_rule_reorder(q, body, m):
        db = rules_db()
        for i, rid in enumerate(body.get("ids") or []):
            r = next((x for x in db["rows"] if x["id"] == int(rid)), None)
            if r:
                r["priority"] = i + 1
        S.save(RULES_KEY, db)
        apply_rules()
        return ok(True)
    R.append(["PUT", r"^/rule/reorder$", r_rule_reorder])

    def r_rule_hits(q, b, m):
        rid = int(q.get("ruleId", 0))
        with LOCK:
            rows = [h for h in HITS if h.get("ruleId") == rid][:80]
        return ok(rows)
    R.append(["GET", r"^/rule/hits$", r_rule_hits])

    # ---- 订阅 / 数据源 ----
    def subs():
        ns = node_store()
        default = [{"id": 1, "name": "矩阵节点源(内置)", "url": D["MATRIX"], "autoFetch": True,
                    "lastFetch": ns["updatedAt"] * 1000 if ns.get("updatedAt") else None,
                    "kind": "matrix", "nodeCount": ns.get("total", 0)}]
        extra = S.load("subs.json", [])
        for x in extra:
            if x.get("url") == D["MATRIX"]:
                x["lastFetch"] = default[0]["lastFetch"]
                x["nodeCount"] = ns.get("total", 0)
        return default + [x for x in extra if x.get("url") != D["MATRIX"]]
    R.append(["GET", r"^/subscription/list$", lambda q, b, m: ok(subs())])

    def r_sub_add(q, body, m):
        if not body.get("url"):
            return fail("订阅地址不能为空")
        cur = subs()
        s = {"id": max([x["id"] for x in cur] or [0]) + 1, "name": body.get("name") or "数据源",
             "url": body["url"], "autoFetch": bool(body.get("autoFetch", True)),
             "lastFetch": None, "kind": "matrix"}
        S.save("subs.json", [x for x in cur if x["id"] != 1] + [s])
        push_event("sub_fetch", "新增节点数据源 %s" % s["name"], source="订阅")
        return ok(s)
    R.append(["POST", r"^/subscription$", r_sub_add])

    def r_sub_del(q, b, m):
        if int(m[1]) == 1:
            return fail("内置矩阵数据源不可删除")
        S.save("subs.json", [x for x in subs() if x["id"] != int(m[1]) and x["id"] != 1])
        return ok(True)
    R.append(["DELETE", r"^/subscription/(\d+)$", r_sub_del])

    def r_sub_fetch(q, b, m):
        s = next((x for x in subs() if x["id"] == int(m[1])), None)
        if not s:
            return fail("订阅不存在")
        c = cfg()
        old = c.get("nodeSource")
        c["nodeSource"] = s["url"]
        S.save("config.json", c)
        try:
            ns = matrix_sync(force=True)
        finally:
            c2 = cfg()
            c2["nodeSource"] = old if old else D["MATRIX"]
            S.save("config.json", c2)
        if time.time() - ns.get("updatedAt", 0) > 120:
            return fail("数据源拉取失败，已保留现有 %s 个节点" % ns.get("total", 0))
        cur = subs()
        for x in cur:
            if x["id"] == s["id"]:
                x["lastFetch"] = int(time.time() * 1000)
        S.save("subs.json", [x for x in cur if x["id"] != 1])
        return ok({"added": ns.get("total", 0), "nodes": []})
    R.append(["POST", r"^/subscription/fetch/(\d+)$", r_sub_fetch])

    # ---- 事件 ----
    def r_event_list(q, b, m):
        rows = read_events()
        if q.get("type"):
            # 支持 a,b 形式：自动切换面板同时看 auto_switch 与 self_heal
            types = {t for t in str(q["type"]).split(",") if t}
            rows = [e for e in rows if e.get("type") in types]
        if q.get("keyword"):
            kw = str(q["keyword"]).lower()
            hay = ["%s%s%s" % (e.get("message") or "", e.get("detail") or "",
                               e.get("reason") or "") for e in rows]
            rows = [e for e, t in zip(rows, hay) if kw in t.lower()]
        return ok(paginate(rows, q))
    R.append(["GET", r"^/event/list$", r_event_list])

    def r_event_clear(q, b, m):
        with LOCK:
            try:
                open(S.path("events.jsonl"), "w").close()
            except Exception as e:  # noqa: BLE001
                return fail(str(e))
        push_event("sys_op", "事件日志已清空", source="系统")
        return ok(True)
    R.append(["DELETE", r"^/event$", r_event_clear])

    # ---- 系统 ----
    def r_sys_info(q, b, m):
        _, host, _ = sh("hostname", shell=True)
        osr = read_file("/etc/os-release")
        pretty = re.search(r'PRETTY_NAME="([^"]+)"', osr)
        total, avail = mem_kb()
        up = uptime_seconds()
        load = read_file("/proc/loadavg").split()
        china, gfw = GW.list_counts()
        _, mtime, _ = sh(["stat", "-c", "%Y", P["CHINA_LIST"]])
        _, out, _ = sh(["ip", "-o", "-4", "addr", "show", "scope", "global"])
        # ip -o 行形如 "2: eth0 inet 192.168.1.100/24 brd … scope global eth0"，接口名在行首而非 dev 后
        addrs = [(addr, dev) for dev, addr in
                 re.findall(r"^\s*\d+:\s+(\S+)\s+inet\s+([\d./]+)", out or "", re.M)
                 if dev != P["WG_IF"]]
        lan = GW.lan()
        return ok({"hostname": "%s (旁路由)" % host.strip(),
                   "mode": "same-subnet-bypass",
                   "lanIf": lan["lanIf"], "lanIp": lan["lanIp"],
                   "lanPrefix": lan["lanPrefix"], "lanCidr": lan["lanCidr"],
                   "dnsAddr": lan["dnsAddr"],
                   "os": pretty.group(1) if pretty else "Linux",
                   "kernel": "%s %s" % (os.uname().sysname, os.uname().release),
                   "cpu": "%d vCore / 负载 %s" % (os.cpu_count() or 1, load[0] if load else "0"),
                   "memUsed": "%d MB" % max(0, (total - avail) // 1024),
                   "memTotal": "%d MB" % (total // 1024),
                   "uptime": "%dd %dh %dm" % (up // 86400, up % 86400 // 3600, up % 3600 // 60),
                   "loadAvg": " ".join(load[:3]) if load else "-",
                   "gatewayIp": " / ".join("%s (%s)" % (a, d) for a, d in addrs) or "—",
                   "dnsMode": "dnsmasq 分流 (53) + 面板下发 97-panel.conf"
                              + ("，查询日志已开启" if cfg().get("queryLog") else ""),
                   "listUpdatedAt": int((mtime or "").strip() or 0) * 1000,
                   "bootAt": int((time.time() - up) * 1000),
                   "bootAtText": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - up)),
                   "wgStatus": "up" if GW.dump().get("up") else "down",
                   "handshakeAge": GW.handshake_age,
                   "exitIp": GW.exit_ip,
                   "chinaRouteCount": china, "gfwDomainCount": gfw})
    R.append(["GET", r"^/system/info$", r_sys_info])

    def r_reload(q, b, m):
        res = apply_rules()
        china, gfw = GW.list_counts()
        push_event("sys_op", "重载分流配置：国内明细 %s 条 / 分流域名 %s 条" % (china, gfw), source="系统")
        return ok(res)
    R.append(["POST", r"^/system/reload$", r_reload])

    def r_restart(q, b, m):
        rc, out, err = sh(["systemctl", "restart", P["WG_SERVICE"]], timeout=90)
        if rc != 0:
            push_event("node_down", "网关重启失败：" + (err or out).strip()[:200], source="系统")
            return fail("重启 wg-quick 失败: " + (err or out).strip()[:200])
        hs = GW.wait_handshake(G["SWITCH_WAIT"] + 8)
        GW.remeasure()
        push_event("sys_op", "网关重启：wg0 隧道%s" % ("已重建并握手成功" if hs else "重建中(握手未完成)"),
                   source="系统", detail="latency=%s loss=%s" % (GW.latency, GW.latency_loss))
        return ok({"handshake": bool(hs), "latency": GW.latency})
    R.append(["POST", r"^/system/restart$", r_restart])

    def r_backup(q, b, m):
        ns = node_store()
        db = rules_db()
        return ok({"version": 1, "exportedAt": int(time.time() * 1000),
                   "nodes": [{k: n.get(k) for k in NODE_KEYS} for n in (ns.get("manual") or [])],
                   "matrixTotal": ns.get("total", 0), "excluded": ns.get("excluded") or [],
                   "groups": db["groups"], "rules": db["rows"],
                   "subs": [x for x in subs() if x["id"] != 1],
                   "autoSwitch": autoswitch(), "config": live_config()})
    R.append(["GET", r"^/system/backup$", r_backup])

    def r_restore(q, body, m):
        if not isinstance(body, dict):
            return fail("备份文件格式不正确")
        ns = node_store()
        if body.get("nodes") is not None:
            ns["manual"] = []
            nid = 900000
            for row in body["nodes"]:
                nid += 1
                ns["manual"].append(manual_node(row, nid))
        if body.get("excluded") is not None:
            names = set(body["excluded"])
            ns["excluded"] = sorted(names)
            for n in ns.get("rows") or []:
                n["excluded"] = n["name"] in names
        if body.get("nodes") is not None or body.get("excluded") is not None:
            save_nodes(ns, flush=True)
        db = rules_db()
        if body.get("groups"):
            db["groups"] = body["groups"]
        if body.get("rules") is not None:
            db["rows"] = body["rules"]
            db["seq"] = max([r.get("id", 0) for r in db["rows"]] or [1000])
        S.save(RULES_KEY, db)
        if body.get("subs") is not None:
            S.save("subs.json", body["subs"])
        if body.get("autoSwitch"):
            a = dict(DEFAULT_AUTOSWITCH)
            a.update(body["autoSwitch"])
            S.save("autoswitch.json", a)
        if body.get("config"):
            c = dict(DEFAULT_CONFIG)
            c.update({k: v for k, v in body["config"].items()
                      if k in ("queryLog", "latencyTarget", "exitCheckUrl", "nodeSource")})
            S.save("config.json", c)
            if body["config"].get("listUpdateAt"):
                write_cron(body["config"]["listUpdateAt"])
        apply_rules()
        push_event("sys_op", "恢复备份：手动节点 %s / 规则 %s / 隐藏节点 %s" %
                   (len(ns.get("manual") or []), len(rules_db()["rows"]),
                    len(ns.get("excluded") or [])), source="系统")
        return ok(True)
    R.append(["POST", r"^/system/restore$", r_restore])

    R.append(["GET", r"^/system/config$", lambda q, b, m: ok(live_config())])

    def r_cfg_put(q, body, m):
        c = cfg()
        # 网络地址是现算的，不落 config.json（避免换网络后备份里带出旧地址误导）
        for k in ("wanIf", "wanGw", "lanIf", "lanIp", "lanPrefix", "lanCidr", "dnsAddr", "wgLan"):
            c.pop(k, None)
        changed = {k: body[k] for k in ("queryLog", "latencyTarget", "exitCheckUrl", "nodeSource",
                                        "mssClamp", "listUpdateAt") if k in body and body[k] != c.get(k)}
        c.update(changed)
        S.save("config.json", c)
        notes = []
        if "mssClamp" in changed:
            spec = ["iptables", "-t", "mangle", "-C", "ROUTE_GW_MSS", "-p", "tcp",
                    "--tcp-flags", "SYN,RST", "SYN", "-j", "TCPMSS", "--clamp-mss-to-pmtu"]
            if changed["mssClamp"]:
                rc, _, e = sh(spec)
                if rc != 0:
                    rc, _, e = sh(["iptables", "-t", "mangle", "-A", "ROUTE_GW_MSS", "-p", "tcp",
                                   "--tcp-flags", "SYN,RST", "SYN", "-j", "TCPMSS", "--clamp-mss-to-pmtu"])
            else:
                rc, _, e = sh(["iptables", "-t", "mangle", "-F", "ROUTE_GW_MSS"])
            notes.append("MSS 钳制%s" % ("已开启" if changed["mssClamp"] else "已关闭")
                         if rc == 0 else "MSS 规则失败: " + e.strip()[:120])
        if "listUpdateAt" in changed:
            notes.append(write_cron(changed["listUpdateAt"]))
        if "queryLog" in changed:
            apply_rules()
            notes.append("dnsmasq 查询日志%s" % ("已开启(开始统计规则命中)" if changed["queryLog"] else "已关闭(停止统计)"))
        if "latencyTarget" in changed:
            GW.remeasure()
            notes.append("隧道延迟实测目标改为 %s" % changed["latencyTarget"])
        push_event("sys_op", "更新网关基础配置：%s" % (", ".join(changed) or "无变化"),
                   source="系统", detail="; ".join(notes) if notes else "无项变更")
        return ok(live_config())
    R.append(["PUT", r"^/system/config$", r_cfg_put])

    def r_as_get(q, b, m):
        a = autoswitch()
        a["availableGroups"] = sorted({n.get("group") for n in all_nodes() if n.get("group")})
        a["nodeTotal"] = len(all_nodes())
        return ok(a)
    R.append(["GET", r"^/system/autoswitch$", r_as_get])

    def r_as_put(q, body, m):
        a = autoswitch()
        a.update({k: body[k] for k in ("enabled", "probeType", "interval", "timeout", "failThreshold",
                                       "cooldown", "sameRegionFirst", "groups", "resetDay") if k in body})
        S.save("autoswitch.json", a)
        push_event("sys_op", "自动切换策略已更新(%s，冷却 %ss，候选组 %s)" %
                   ("启用" if a["enabled"] else "停用", a["cooldown"],
                    ",".join(a.get("groups") or ["全部 WG 分组"])), source="系统",
                   detail="故障阈值 %s 次 / 同区域优先 %s" % (a["failThreshold"], a["sameRegionFirst"]))
        return ok(a)
    R.append(["PUT", r"^/system/autoswitch$", r_as_put])

    def r_probe(q, b, m):
        ns = node_store()
        pool = [n for n in (ns.get("rows") or []) if n.get("switchable") and not n.get("excluded")]
        ids = [n["id"] for n in pool if n.get("source") == "manual" or n.get("current")]
        ids += [n["id"] for n in sorted(pool, key=lambda n: n["delay"]
                                        if n.get("delay") is not None else 1e9)[:60]]
        ids = list(dict.fromkeys(ids))[:120]
        online, fault = apply_probe_results(probe_ids(ids))
        push_event("sys_op", "手动探测完成：本轮 %s/%s 可达，判故障 %s" % (online, len(ids), fault),
                   source="探测", detail="ICMP 走 WAN 网卡(%s)直探节点入口，绕过策略路由" % GW.wan()[1])
        return ok({"online": online, "total": len(ids)})
    R.append(["POST", r"^/system/probe-now$", r_probe])

    def r_password(q, body, m):
        old, new = body.get("oldPassword") or "", body.get("newPassword") or ""
        if len(new) < 8:
            return fail("新密码至少 8 位")
        user = getattr(CTX, "user", None)
        if not user or not verify_user(user, old):
            return fail("原密码不正确", 403)
        c = credentials()
        for u in c["users"]:
            if u["username"] == user:
                salt = secrets.token_hex(16)
                u.update({"salt": salt, "iterations": ITERATIONS, "hash": hash_pw(new, salt)})
        S.save("credentials.json", c)
        # 改密一旦写坏就是把自己锁在面板外面，所以先验一次再宣布成功
        if not verify_user(user, new):
            push_event("sys_op", "账号 %s 改密后校验失败，凭证已回滚" % user, source="系统")
            return fail("改密后校验失败，请重试或改用命令行 --set-password", 500)
        p = S.path("INITIAL_PASSWORD.txt")
        if os.path.exists(p):
            os.remove(p)
        push_event("sys_op", "账号 %s 修改了登录密码" % user, source="系统")
        return ok(True)
    R.append(["POST", r"^/system/password$", r_password])

    def r_tunnel(q, b, m):
        d = GW.dump(force=True)
        return ok({"wgUp": d.get("up"), "peer": d.get("peer"), "fwmark": d.get("fwmark"),
                   "listen": d.get("listen"), "rules": GW.ip_rules(),
                   "mainRoutes": GW.route_count(), "tableRoutes": GW.table_count(),
                   "latency": GW.latency, "loss": GW.latency_loss, "exitIp": GW.exit_ip,
                   "queryLog": bool(cfg().get("queryLog")), "hitsTracked": len(HITS),
                   "autoswitch": autoswitch(), "lastSwitch": S.load("last_switch.json", {"t": 0})["t"]})
    R.append(["GET", r"^/system/tunnel$", r_tunnel])

    # ---- 延迟历史(仪表盘曲线) ----
    def r_latency(q, b, m):
        with LOCK:
            series = list(LATENCY["series"]) or list(S.load("latency.json", []))
        vals = [s["ms"] for s in series if s.get("ms") is not None]
        return ok({"series": series[-G["LATENCY_KEEP"]:],
                   "current": GW.latency, "loss": GW.latency_loss,
                   "target": cfg()["latencyTarget"], "every": G["PING_EVERY"],
                   "measuredAt": int(GW.measured_at * 1000),
                   "stats": {"samples": len(vals), "min": min(vals) if vals else None,
                             "max": max(vals) if vals else None,
                             "avg": round(sum(vals) / len(vals), 1) if vals else None,
                             "lossSamples": len([s for s in series if s.get("loss")]),
                             "windowSec": len(series) * G["PING_EVERY"]}})
    R.append(["GET", r"^/dashboard/latency$", r_latency])

    # ---- DNS 管理 ----
    def r_dns_overview(q, b, m):
        china, gfw = GW.list_counts()
        _, ver, _ = sh(["dnsmasq", "--version"], timeout=8)
        act, en = unit_state("dnsmasq")
        main_txt = read_file(P["DNS_MAIN"])
        files = [file_view(P["PANEL_CONF"], "面板下发(分流规则页)"),
                 file_view(P["CUSTOM_CONF"], "手工补充域名(不被 cron 覆盖)"),
                 file_view(P["GFW_CONF"], "gfwlist 生成(cron 每日更新)")]
        db = rules_db()
        return ok({"views": dns_views(),
                   "listPath": P["CHINA_LIST"],
                   "service": {"active": act, "enabled": en, "listening": act == "active",
                               "version": (ver or "").splitlines()[0][:60] if ver else ""},
                   "queryLog": bool(cfg().get("queryLog")),
                   "baseUpstreams": re.findall(r"^server=([\d.]+)$", main_txt, re.M),
                   "proxyUpstream": G["GFW_DNS"], "directUpstream": G["DIRECT_DNS"],
                   "local": "%s:53" % P["LOCAL_DNS"],
                   "counts": {"chinaIp": china, "gfwDomain": gfw,
                              "panelDomain": files[0]["serverLines"] + files[0]["addressLines"],
                              "customDomain": files[1]["serverLines"],
                              "ruleDomain": len([r for r in db["rows"]
                                                 if r.get("type") == "domain" and r.get("enabled")]),
                              "ruleIp": len([r for r in db["rows"]
                                             if r.get("type") in ("ip", "geoip") and r.get("enabled")])},
                   "files": files,
                   "observed": {"hitsTracked": len(HITS), "clients": len(CLIENTS)}})
    R.append(["GET", r"^/dns/overview$", r_dns_overview])

    def r_dns_query(q, b, m):
        body = b or {}
        name = str(q.get("domain") or body.get("domain") or "").strip().strip(".")
        if not name or not DOMAIN_OK_RE.match(name):
            return fail("域名格式不正确")
        qtype = str(q.get("type") or body.get("type") or "A").upper()
        if qtype not in DNS_QTYPES:
            return fail("只支持 A / AAAA 查询")
        view = str(q.get("view") or body.get("view") or "all")
        rows = []
        for v in dns_views():
            if view in ("all", v["key"]):
                rows.append(dict(dns_query(v["server"], name, qtype), key=v["key"], label=v["label"]))
        push_event("sys_op", "DNS 解析测试 %s(%s)" % (name, qtype), source="DNS 管理",
                   detail="; ".join("%s → %s" % (r["label"],
                                                 ",".join(r["ips"]) if r["ok"] and r["ips"]
                                                 else (r["error"] or r["rcode"] or "无记录"))
                                    for r in rows)[:500])
        return ok({"domain": name, "type": qtype, "results": rows, "matches": dns_matches(name)})
    R.append(["GET", r"^/dns/query$", r_dns_query])

    def r_dns_hits(q, b, m):
        try:
            n = max(1, min(G["HIT_KEEP"], int(q.get("limit") or 80)))
        except Exception:  # noqa: BLE001
            n = 80
        with LOCK:
            rows = list(HITS)[:n]
        return ok({"rows": rows, "clients": len(CLIENTS), "tracked": G["HIT_KEEP"]})
    R.append(["GET", r"^/dns/hits$", r_dns_hits])

    # ---- 客户端设备 ----
    def r_client_list(q, b, m):
        neigh, leases = lan_neighbors(), dnsmasq_leases()
        now_ms = int(time.time() * 1000)
        rows = []
        for ip in set(neigh) | set(leases) | set(CLIENTS):
            if not is_ip(ip):
                continue
            c, lease, base = CLIENTS.get(ip) or {}, leases.get(ip) or {}, neigh.get(ip) or {}
            last = c.get("last") or None
            rows.append({"ip": ip, "dev": base.get("dev"), "mac": base.get("mac") or lease.get("mac"),
                         "neighState": base.get("state"), "hostname": lease.get("hostname"),
                         "leaseExpires": lease.get("expires"),
                         "queries": c.get("count", 0), "proxy": c.get("proxy", 0),
                         "direct": c.get("direct", 0), "reject": c.get("reject", 0),
                         "types": c.get("types") or {},
                         "recent": list(reversed(c.get("domains") or []))[:6],
                         "lastQuery": last, "firstSeen": c.get("first"),
                         "idle": max(0, (now_ms - last) // 1000) if last else None})
        for r in rows:
            r["active"] = bool(r["idle"] is not None and r["idle"] <= G["CLIENT_ACTIVE"])
        if q.get("active"):                        # 过滤要在分页前做，否则每页条数会缩水
            rows = [r for r in rows if r["active"]]
        kw = str(q.get("keyword") or "").lower()
        if kw:
            rows = [r for r in rows if kw in " ".join(
                [str(r.get("ip") or ""), str(r.get("mac") or ""), str(r.get("hostname") or ""),
                 " ".join(r["recent"])]).lower()]
        rows.sort(key=lambda r: (-r["queries"], r["ip"]))
        return ok(dict(paginate(rows, q),
                       stat={"total": len(rows), "active": len([r for r in rows if r["active"]]),
                             "activeWindow": G["CLIENT_ACTIVE"],
                             "neigh": len(neigh), "leases": len(leases),
                             "quiet": len([r for r in rows if not r["queries"]]),
                             "proxyTotal": sum(r["proxy"] for r in rows),
                             "directTotal": sum(r["direct"] for r in rows)}))
    R.append(["GET", r"^/client/list$", r_client_list])

    # ---- 切换历史 ----
    def r_switch_history(q, b, m):
        def record(attempt, outcome):
            e = attempt or outcome
            # 事件 time 是毫秒，cost 统一换算成秒(与事件里自带的 cost 字段同一单位)
            cost = (outcome or {}).get("cost")
            if cost is None and attempt and outcome:
                cost = round(max(0, outcome["time"] - attempt["time"]) / 1000, 1)
            return {"id": e["id"], "at": e["time"],
                    "trigger": SWITCH_TRIGGERS.get(e.get("type"), "隧道事件"),
                    "from": e.get("from") or (outcome or {}).get("from"),
                    "to": e.get("to") or (outcome or {}).get("to"),
                    "reason": e.get("reason") or (outcome or {}).get("reason") or "",
                    "result": switch_result(outcome),
                    "cost": cost, "latency": (outcome or {}).get("latency"),
                    "loss": (outcome or {}).get("loss"),
                    "attemptMsg": (attempt or {}).get("message") or "",
                    "outcomeMsg": (outcome or {}).get("message") or ""}
        pending, rows, done = {}, [], {}
        for e in reversed(read_events()):      # read_events 是新→旧，配对必须按时间正序走
            if e.get("type") not in SWITCH_TYPES:
                continue
            # 不带 to 的 node_down/node_up 是探测判故障/恢复，不是切换动作；只有"自愈没跑成"
            # 这类没有目标节点的 self_heal 才算一次切换尝试，否则切换历史会被探测噪声填满。
            if not e.get("to") and e.get("type") != "self_heal":
                continue
            to = e.get("to")
            if e["type"] in ("manual_switch", "auto_switch"):
                if to and to in pending:
                    rows.append(record(pending.pop(to), None))
                if to:
                    pending[to] = e
                else:
                    rows.append(record(e, None))
            elif to and to in pending:
                rows.append(record(pending.pop(to), e))
                done[to] = e["time"]
            elif to and e["type"] == "self_heal" and done.get(to, 0) >= e["time"] - 60000:
                continue        # 同一次切换的"自愈成功"汇总事件，已由发起+握手段占一行，不重复展示
            else:
                rows.append(record(None, e))
        rows += [record(e, None) for e in pending.values()]
        rows.sort(key=lambda r: r["at"], reverse=True)
        if q.get("result"):
            rows = [r for r in rows if r["result"] == q["result"]]
        kw = str(q.get("keyword") or "").lower()
        if kw:
            rows = [r for r in rows if kw in " ".join(
                str(r.get(k) or "") for k in ("from", "to", "reason", "attemptMsg", "outcomeMsg")).lower()]
        costs = [r["cost"] for r in rows if r.get("cost") is not None]
        cur = current_node()
        return ok(dict(paginate(rows, q),
                       summary={"total": len(rows),
                                "success": len([r for r in rows if r["result"] == "success"]),
                                "fail": len([r for r in rows if r["result"] in ("fail", "rollback")]),
                                "pending": len([r for r in rows if r["result"] == "pending"]),
                                "avgCost": round(sum(costs) / len(costs), 1) if costs else None},
                       current=cur["name"] if cur else None,
                       lastSwitchAt=int(S.load("last_switch.json", {"t": 0})["t"] * 1000),
                       autoswitch=autoswitch()))
    R.append(["GET", r"^/switch/history$", r_switch_history])

    # ---- 日志查看器 ----
    def r_log_units(q, b, m):
        out = []
        for key, u in G["LOG_UNITS"].items():
            if u.get("unit"):
                act, en = unit_state(u["unit"])
                out.append({"key": key, "label": u["label"], "kind": "journal", "unit": u["unit"],
                            "active": act, "enabled": en})
            else:
                fv = file_view(u["file"], u["label"])
                out.append({"key": key, "label": u["label"], "kind": "file", "file": fv,
                            "active": "active" if fv["exists"] else "absent", "enabled": "-"})
        return ok(out)
    R.append(["GET", r"^/system/log-units$", r_log_units])

    def r_sys_logs(q, b, m):
        key = q.get("unit") or "dnsmasq"
        u = G["LOG_UNITS"].get(key)
        if not u:
            return fail("日志源不在白名单内: %s" % key)
        try:
            want = max(20, min(G["JOURNAL_MAX"], int(q.get("lines") or 200)))
        except Exception:  # noqa: BLE001
            want = 200
        kw = str(q.get("keyword") or "")[:64].lower()
        if u.get("unit"):
            rc, out, err = sh(["journalctl", "-u", u["unit"], "-n", str(want * 3),
                               "--no-pager", "-o", "short-iso"], timeout=25)
            if rc != 0:
                return fail("journalctl 读取失败: " + (err or out).strip()[:180])
            raw, source = out.splitlines(), u["unit"]
        else:
            raw, source = tail_lines(u["file"], want * 3), u["file"]
        rows = []
        for ln in raw:
            if kw and kw not in ln.lower():
                continue
            if u.get("unit"):
                head, _, rest = ln.partition(" ")     # short-iso: 时间戳 与 其余内容分开显示
                rows.append({"t": journal_ts_ms(ln), "head": head, "text": (rest or ln)[:400]})
            else:
                rows.append({"t": None, "head": "", "text": ln[:400]})
        rows.reverse()                         # 一律最新在上，和事件页一致
        return ok({"unit": key, "label": u["label"], "source": source, "lines": rows[:want],
                   "requested": want, "matched": len(rows), "scanned": len(raw)})
    R.append(["GET", r"^/system/logs$", r_sys_logs])

    # ---- 数据源(国内 IP / gfwlist / 节点矩阵) ----
    def r_list_status(q, b, m):
        china, gfw = GW.list_counts()
        ns = node_store()
        files = [file_view(P["CHINA_LIST"], "国内 IP 明细表(策略路由用)"),
                 file_view(P["GFW_CONF"], "gfwlist 域名(dnsmasq 分流)"),
                 file_view(P["CUSTOM_CONF"], "手工补充域名"),
                 file_view(P["PANEL_CONF"], "面板下发域名"),
                 file_view(P["UPDATE_LISTS"], "更新脚本"),
                 file_view(P["CRON_LISTS"], "定时任务"),
                 file_view(P["LIST_LOG"], "更新日志")]
        return ok({"counts": {"chinaIp": china, "gfwDomain": gfw},
                   "files": files, "cronAt": cron_time(), "cronNext": next_cron_at(cron_time()),
                   "scriptOk": os.access(P["UPDATE_LISTS"], os.X_OK),
                   "logTail": tail_lines(P["LIST_LOG"], 40),
                   "matrix": {"url": cfg().get("nodeSource") or D["MATRIX"], "total": ns.get("total", 0),
                              "updatedAt": int(ns.get("updatedAt", 0)) * 1000,
                              "builtAt": ns.get("builtAt"), "fetchInterval": G["MATRIX_FETCH_INTERVAL"]},
                   "subs": subs()})
    R.append(["GET", r"^/list/status$", r_list_status])

    def r_list_update(q, b, m):
        """手动跑一次既有的 update-lists.sh：只复用已验证过的下发路径，不在面板里重写下载逻辑。"""
        rc, out, err = sh([P["UPDATE_LISTS"]], timeout=150)
        china, gfw = GW.list_counts()
        tail = [l[:300] for l in ((out + "\n" + err).strip().splitlines()[-15:])]
        push_event("sys_op", "手动更新分流数据源：国内 IP %s 条 / 分流域名 %s 条(%s)" %
                   (china, gfw, "成功" if rc == 0 else "脚本返回 rc=%s" % rc),
                   source="数据源", detail="\n".join(tail[-6:])[:500])
        return ok({"rc": rc, "china": china, "gfw": gfw, "log": tail},
                  "数据源更新完成" if rc == 0 else "更新脚本返回非 0，详见更新日志")
    R.append(["POST", r"^/list/update$", r_list_update])

    # EXTENSION_POINT: 协议流量拆分/接口计数明细/更多日志源等观测接口在此追加
    return R


ROUTES = []


# ============================================================ 登录接口
def h_login(q, body, m):
    ip = getattr(CTX, "ip", "0.0.0.0")
    if login_limited(ip):
        push_event("login", "登录尝试被限流", source="系统", detail="ip=%s" % ip)
        return fail("失败次数过多，请 10 分钟后再试", 429)
    username = (body.get("username") or "").strip()
    if not verify_user(username, body.get("password") or ""):
        LOGIN_FAIL.setdefault(ip, deque(maxlen=64)).append(time.time())
        push_event("login", "登录失败：%s" % (username or "(空账号)"), source="系统", detail="ip=%s" % ip)
        return fail("账号或密码不正确", 401)
    sid = new_session(username, ip)
    push_event("login", "账号 %s 登录成功" % username, source="系统", detail="ip=%s" % ip)
    resp_header("Set-Cookie", "%s=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d"
                % (D["COOKIE"], sid, G["SESSION_TTL"]))
    return ok({"username": username}, "登录成功")


def h_logout(q, body, m):
    drop_session(getattr(CTX, "sid", None))
    push_event("login", "账号 %s 退出登录" % getattr(CTX, "user", "-"), source="系统")
    resp_header("Set-Cookie", "%s=; Path=/; HttpOnly; Max-Age=0" % D["COOKIE"])
    return ok(True, "已退出")


def h_user_info(q, body, m):
    sid = getattr(CTX, "sid", None)
    sess = SESSIONS.get(sid) if sid else None
    if not sess or sess.get("exp", 0) < time.time():
        return fail("未登录", 401)
    CTX.user = sess["user"]
    return ok({"username": sess["user"]})


def resp_header(key, value):
    if not hasattr(CTX, "headers"):
        CTX.headers = []
    CTX.headers.append((key, value))


# ============================================================ HTTP 层
PUBLIC = ("/login", "/logout", "/user/info")
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
                ".jpg": "image/jpeg", ".gif": "image/gif", ".ico": "image/x-icon",
                ".json": "application/json", ".map": "application/json",
                ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf"}


class Handler(BaseHTTPRequestHandler):
    server_version = "GwAdmin/" + API_VERSION

    def log_message(self, fmt, *args):        # 静音访问日志，避免刷满 /var/log/syslog
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in getattr(CTX, "headers", []):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _sid(self):
        ck = http.cookies.SimpleCookie()
        try:
            ck.load(self.headers.get("Cookie", ""))
        except Exception:  # noqa: BLE001
            return None
        c = ck.get(D["COOKIE"])
        return c.value if c else None

    def _guard(self, path):
        CTX.sid = self._sid()
        if path in PUBLIC:
            return True
        sess = SESSIONS.get(CTX.sid) if CTX.sid else None
        if not sess or sess.get("exp", 0) < time.time():
            self._json(fail("未登录或会话已过期", 401))     # HTTP 200 + code 401，交前端跳登录
            return False
        CTX.user = sess["user"]
        return True

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except Exception:  # noqa: BLE001
            n = 0
        if n <= 0:
            return {}
        raw = self.rfile.read(min(n, 8 * 1024 * 1024))
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def _api(self, method):
        CTX.headers, CTX.ip = [], self.client_address[0]
        path_part, _, query = self.path.partition("?")
        path = re.sub(r"^/api", "", path_part) or "/"
        q = {k: v[0] for k, v in parse_qs(query).items() if v}
        if not self._guard(path):
            return
        for mth, rex, fn in ROUTES:
            mo = re.match(rex, path) if mth == method else None
            if mo:
                try:
                    res = fn(q, self._body(), mo)
                except Exception as e:  # noqa: BLE001
                    log("接口异常", method, path, repr(e))
                    res = fail("服务端异常: %s" % e, 500)
                return self._json(res)
        self._json(fail("接口未实现: %s %s" % (method, path), 404))

    def do_GET(self):
        if self.path.split("?")[0].startswith("/api"):
            return self._api("GET")
        return self._static()

    def do_POST(self):
        return self._api("POST")

    def do_PUT(self):
        return self._api("PUT")

    def do_DELETE(self):
        return self._api("DELETE")

    def _static(self):
        dist = os.path.abspath(D["DIST"])
        rel = self.path.split("?")[0].lstrip("/") or "index.html"
        target = os.path.abspath(os.path.join(dist, rel))
        if not target.startswith(dist):
            return self._json(fail("非法路径", 403))
        if not os.path.isfile(target):
            # 只有"无扩展名"的路径才回落单页(深链)；缺失的静态资源必须如实 404，
            # 否则浏览器把 HTML 当 JS 解析，报错完全看不出根因
            if os.path.splitext(rel)[1]:
                return self._json(fail("资源不存在: /%s" % rel, 404), status=404)
            target = os.path.join(dist, "index.html")
        if not os.path.isfile(target):
            return self._json(ok({"name": "分流网关管理面板", "api": "/api",
                                  "hint": "前端未构建：npm run build 后把 dist 放到 %s" % dist}))
        ext = os.path.splitext(target)[1].lower()
        data = read_bytes(target)
        if data is None:
            return self._json(fail("读取文件失败", 500))
        self.send_response(200)
        self.send_header("Content-Type", STATIC_TYPES.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache" if ext == ".html" else "public, max-age=86400")
        self.end_headers()
        self.wfile.write(data)


def read_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:  # noqa: BLE001
        return None


# ============================================================ 启动 / CLI
def reconcile_wg_conf():
    """面板启动时让 wg0.conf 跟随运行中的隧道，而不是反过来动隧道。
    上次切换/回滚若在 syncconf 前后被中断，文件里的 [Peer] 会跑到现实前面；
    此时若按文件再同步一次，下挂设备会连上一个从未验证过的节点，所以只修文件。"""
    live_pk, live_ep = GW.live_peer()
    if not live_pk or not live_ep:
        return
    file_pk, file_ep = GW.conf_peer()
    if file_pk == live_pk and file_ep == live_ep:
        return
    written, err = GW.write_wg_conf(live_pk, live_ep)
    if written:
        log("wg0.conf 已对齐到运行中的隧道 peer %s" % live_ep)
        push_event("self_heal", "wg0.conf 的 [Peer] 与运行中的隧道不一致，已按隧道修正",
                   source="网关", reason="文件=%s 隧道=%s" % (file_ep or "缺", live_ep))
    else:
        log("wg0.conf 对齐失败:", err)


def bootstrap():
    load_sessions()
    try:
        reconcile_wg_conf()
    except Exception as e:  # noqa: BLE001
        log("启动时对齐 wg0.conf 失败:", e)
    try:
        # 面板停机期间规则/查询日志开关可能被改过，起来先和 dnsmasq、明细路由对齐一次
        apply_rules()
    except Exception as e:  # noqa: BLE001
        log("启动时对齐分流规则失败:", e)
    for name, fn in (("采样", traffic_loop), ("健康/自愈", health_loop),
                     ("矩阵同步", matrix_loop), ("查询日志", dnsmasq_tail_loop), ("落盘", flush_loop)):
        threading.Thread(target=fn, daemon=True, name=name).start()
    log("后台线程: 采样/健康/矩阵/日志/落盘 已启动")


def cli(args):
    # systemd/文档里一律用 --status 这类长选项，命令行传进来的前导破折号在这里剥掉
    cmd = args[0].lstrip("-") if args else "status"
    if cmd == "status":
        d = GW.dump(force=True)
        peer = d.get("peer") or {}
        nodes = all_nodes()
        cur = next((n for n in nodes if n.get("current")), None)
        gw, wan = GW.wan()
        china, gfw = GW.list_counts()
        hs = peer.get("handshake", 0)
        print("wg0            :", "up" if d.get("up") else "down", " fwmark:", d.get("fwmark"))
        print("当前节点        :", cur["name"] if cur else "(节点池未匹配到 peer)")
        print("endpoint       :", peer.get("endpoint") or "-")
        f_pk, f_ep = GW.conf_peer()
        print("wg0.conf      :", "与隧道一致" if (f_pk == peer.get("pubkey") and f_ep ==
              (peer.get("endpoint") or "").strip("()")) else "不一致(文件=%s)" % (f_ep or "缺"))
        print("握手距今        :", ("%ds" % int(time.time() - hs)) if hs else "从未")
        print("rx / tx        :", peer.get("rx"), "/", peer.get("tx"))
        lat, loss = GW.ping_latency()
        print("隧道延迟        : %s ms  丢包: %s  出口: %s" %
              (lat, loss, GW.check_exit_ip(cfg()["exitCheckUrl"]) or "-"))
        print("WAN            :", wan, "via", gw)
        print("路由           : main=%s 表%s=%s 策略=%s 条" %
              (GW.route_count(), G["WG_TABLE"], GW.table_count(), len(GW.ip_rules())))
        print("数据源         : 国内 IP %s 条 / 分流域名 %s 条" % (china, gfw))
        print("节点池         : 共 %s 在线 %s 可切换 %s (矩阵同步于 %s)" %
              (len(nodes), len([n for n in nodes if n.get("status") == "online"]),
               len([n for n in nodes if n.get("switchable")]),
               time.strftime("%m-%d %H:%M", time.localtime(node_store().get("updatedAt", 0)))))
        st = S.load("traffic.json", {})
        print("今日流量      :", st.get("days", {}).get(day_key()))
        print("规则           :", len(rules_db()["rows"]), "条 / 面板下发文件", P["PANEL_CONF"])
        return 0
    if cmd == "sync":
        print("节点池:", matrix_sync(force=True).get("total"))
        return 0
    if cmd == "probe":
        ids = [n["id"] for n in node_store().get("rows") or []][:int(args[1] if len(args) > 1 else 40)]
        print("在线/故障:", apply_probe_results(probe_ids(ids)))
        return 0
    if cmd == "switch":
        print(json.dumps(do_switch(args[1], "manual_switch", "CLI 操作"), ensure_ascii=False))
        return 0
    if cmd == "restore":
        # wg0.conf 与运行中的隧道分叉时的人工修复：以隧道为准重写配置文件，绝不改动在跑的 peer
        live_pk, live_ep = GW.live_peer()
        if not live_pk or not live_ep:
            print("隧道当前没有可用 peer(wg0 未起来)，不能以隧道为准；请先 systemctl restart wg-quick@wg0")
            return 1
        f_pk, f_ep = GW.conf_peer()
        if f_pk == live_pk and f_ep == live_ep:
            print("wg0.conf 与隧道一致(%s)，无需修复" % live_ep)
            return 0
        written, err = GW.write_wg_conf(live_pk, live_ep)
        print(("已按隧道修正 wg0.conf: %s → %s" % (f_ep or "缺", live_ep)) if written
              else ("修正失败: %s" % err))
        return 0 if written else 1
    if cmd == "apply-rules":
        print(apply_rules())
        return 0
    if cmd == "events":
        for e in read_events(25):
            print(time.strftime("%m-%d %H:%M:%S", time.localtime(e["time"] / 1000)),
                  e["type"], "|", e["message"])
        return 0
    if cmd == "set-password":
        if len(args) < 3:
            print("用法: --set-password <账号> <新密码>")
            return 2
        c = credentials()
        salt, pw = secrets.token_hex(16), args[2]
        for u in c["users"]:
            if u["username"] == args[1]:
                u.update({"salt": salt, "hash": hash_pw(pw, salt)})
                S.save("credentials.json", c)
                p = S.path("INITIAL_PASSWORD.txt")
                if os.path.exists(p):
                    os.remove(p)
                print("账号 %s 密码已更新" % args[1])
                return 0
        c["users"].append({"username": args[1], "salt": salt, "iterations": ITERATIONS,
                           "hash": hash_pw(pw, salt), "createdAt": int(time.time() * 1000)})
        S.save("credentials.json", c)
        print("账号 %s 已创建并设置密码" % args[1])
        return 0
    print("用法: gw_server.py [--serve] | --status | --sync | --probe N | --switch <节点ID> | --restore | "
          "--apply-rules | --events | --set-password <账号> <新密码>")
    return 2


def main(argv):
    args = argv[1:]
    global ROUTES
    ROUTES = routes_table()
    if args and args[0].startswith("--") and args[0] != "--serve":
        return cli(args)
    pw = ensure_admin(os.environ.get("GW_ADMIN_PASSWORD"))
    if pw:
        print("已创建默认账号 admin，初始密码见 %s (权限 600，登录后请立即在「系统设置」修改)"
              % S.path("INITIAL_PASSWORD.txt"))
    bootstrap()
    try:
        srv = ThreadingHTTPServer((D["HOST"], D["PORT"]), Handler)
    except OSError as e:
        log("监听失败:", e)
        return 1
    log("面板监听 http://%s:%d · dist=%s · data=%s" % (D["HOST"], D["PORT"], D["DIST"], D["DATA"]))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        S.save_dirty()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
