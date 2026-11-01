# 让 LAN 客户端访问 ZeroTier / Tailscale 网络

目标：J1900 下面的电脑（包括实体路由器下面的设备）继续把 `J1900` 当默认网关，
不需要安装 ZeroTier/Tailscale，也能访问 overlay 网络里的其它主机。

> 本文用 `<ZT_NETWORK_ID>`、`<ZT_PEER_IP>` 这类占位符，不要把真实网络 ID 和地址提交到仓库。

## 1. 原理

J1900 同时是：

- LAN 网关 `192.168.0.125`（以实际为准）
- ZeroTier/Tailscale 成员（例如 `ztxxxxxxx` / `tailscale0`）

LAN 客户端访问 overlay 网段时，J1900 做 **NAT 转发**：

```text
LAN 192.168.0.0/24  --源地址 NAT 成 J1900 的 overlay IP-->  overlay 主机
```

这样客户端不需要加静态路由，overlay 主机看到的是 J1900 的 overlay 地址。
适合“只让 LAN 访问 overlay 主机”的常见场景。

## 2. 安装 ZeroTier

### 自动方式（网络 ID 不落仓库）

```bash
# 在网关机内
sudo ZT_NETWORK_ID=<ZT_NETWORK_ID> bash install.sh
# 或单独安装
sudo bash install-zerotier.sh <ZT_NETWORK_ID>
```

`install-zerotier.sh` 会：

1. 安装 `zerotier-one` 并 enable；
2. `zerotier-cli join <ZT_NETWORK_ID>`；
3. 等待网络状态 `OK`；
4. `systemctl enable --now route-gw-overlay.service`。

网络 ID 只作为参数传入，不写进脚本/文档。

### 手动方式

```bash
curl -fsSL https://install.zerotier.com | sudo bash
sudo zerotier-cli join <ZT_NETWORK_ID>
# 到 ZeroTier Central 授权这台成员（私有网络需要）
sudo zerotier-cli listnetworks
```

看到 `OK` 和 `zt...` 接口、`<ZT_LOCAL_IP>` 地址即可。

```bash
ip -br addr | grep zt
ip route get <ZT_PEER_IP>      # 应该 dev ztxxxxxxx
ping -c3 <ZT_PEER_IP>
```

## 3. 启用 overlay NAT 服务

仓库已带：

- `files/usr/local/bin/overlay-route-up.sh`
- `files/usr/local/bin/overlay-route-down.sh`
- `files/etc/systemd/system/route-gw-overlay.service`

`install.sh` 会安装脚本和 unit；检测到 `zerotier-cli`/`tailscale` 时会自动 enable，
否则装好 overlay 后手动：

```bash
sudo systemctl enable --now route-gw-overlay.service
systemctl status route-gw-overlay.service --no-pager
sudo iptables -t nat -S OVERLAY_NAT
sudo iptables -S OVERLAY_FWD
```

脚本自动：

- 从默认路由取 LAN 网卡和 LAN 网段
- 查找 `zt*` / `tailscale0` 接口
- 在**独立链** `OVERLAY_NAT` / `OVERLAY_FWD` 里做 MASQUERADE + FORWARD

独立链很重要：`wg-route-up.sh` 每次重启会 flush `ROUTE_GW_NAT` / `ROUTE_GW_FWD`，
overlay 规则放在自己的链里不会被冲掉。

## 4. 验证

在 J1900 上：

```bash
ping -c3 <ZT_PEER_IP>
sudo iptables -t nat -vnL OVERLAY_NAT
```

在一台 LAN 客户端上（网关指向 J1900）：

```bash
ping <ZT_PEER_IP>
# 或访问 overlay 主机的具体服务
curl http://<ZT_PEER_IP>:<PORT>/
```

预期：`OVERLAY_NAT` 的包计数增长，客户端能 ping 通 overlay 主机。
如果 overlay 主机开了防火墙，ICMP/TCP 可能被拦，这属于目标主机策略，不是 J1900 转发问题。

实测（2026-11-01）：

- J1900 自己 ping `<ZT_PEER_IP>`：3/3 通
- 模拟 0.x 客户端 `192.168.0.250`（网关 `192.168.0.125`）ping `<ZT_PEER_IP>`：3/3 通
- `OVERLAY_NAT` 计数随 ping 增长
- 重启 J1900 后 `zerotier-one` / `route-gw-overlay` 自动 active，客户端再次 ping 通

## 5. 让 overlay 主机主动访问 LAN（可选）

如果只做 LAN → overlay，上面的配置已经够；overlay 回程按 conntrack 放行。

如果还需要 overlay 主机主动访问 LAN：

1. ZeroTier Central 加 Managed Route：`192.168.0.0/24 via <J1900 的 ZT IP>`
2. 在 `overlay-route-up.sh` 的 `OVERLAY_FWD` 里加一条：

```bash
iptables -A OVERLAY_FWD -i "$iface" -d "$LAN_NET" -j ACCEPT
```

3. 不要给 overlay 授权 `0.0.0.0/0` 默认路由，避免和 route-gw 的分流默认路由冲突。

## 6. Tailscale 变体

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --advertise-routes=192.168.0.0/24 --snat-subnet-routes=true
```

J1900 的 `tailscale0` 会被同一个 `overlay-route-up.sh` 自动识别；
LAN 客户端访问 `100.64.0.0/10` 时走 J1900 的 NAT。  
如果要让 tailnet 成员访问 LAN，需要在 Tailscale 管理台批准 `192.168.0.0/24` 子网路由。

## 7. 与策略路由的关系

J1900 有两条分流规则：

```text
32764: from all lookup main suppress_prefixlength 0
32765: not from all fwmark 0xca6c lookup 51820
```

overlay 网段在 main 表里有 connected/managed route，会先命中 `32764`，不会误走 wg0。
排查时看：

```bash
ip route get <ZT_PEER_IP>
```

必须是 `dev ztxxxxxxx`；如果显示 `dev wg0`，说明 overlay 路由没进 main 表。

## 8. 重启持久化

- `route-gw-overlay.service` 已 `enable`，`After=zerotier-one.service`。
- ZeroTier 重启时 `PartOf=zerotier-one.service` 会带动 overlay 服务重启。
- 如果 overlay 接口比服务晚出现，脚本最多等 30 秒；仍未出现则跳过，等下次服务启动/手动重启。
