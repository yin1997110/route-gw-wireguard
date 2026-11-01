# 节点数据源 `data.js` 格式约定

面板的「节点数据源」既可以是公网矩阵，也可以换成一个内网地址（例如
`http://10.0.0.10:3333/data.js`）。本文说明面板实际使用的字段，方便自己实现一个兼容的数据包。

> 本文所有 IP / 公钥都是 RFC 5737 或占位值，不要提交真实 `data.js`。

## 1. 传输与解析

- `POST /api/system/source/test` 会实际拉取一次并校验；保存 `nodeSource` 时后端也会再校验一次。
- 支持 `http://` 和 `https://`；HTTPS 使用自签名证书也可以（面板关闭了证书校验）。
- 内容可以是纯 JSON，也可以是 JS 赋值：

```js
window.VPN_DATA = { ... };
```

后端取第一个 `{` 到最后一个 `}` 之间的内容做 `json.loads`，所以外层变量名随意。
- 当前线上矩阵约 1.3 MB、4000+ 节点；建议服务端直接返回 JSON，不要压缩成需要额外解码的格式。
- 单次拉取超时 45 秒；测试接口 12 秒。

## 2. 顶层结构

```json
{
  "meta": {
    "cols": ["id", "proto", "name", "ip", "port", "cc", "countryCn", "city",
             "alive", "ping", "health", "allowed"],
    "builtAt": "2026-01-01T00:00:00Z",
    "source": "internal-matrix"
  },
  "nodes": [
    [1001, "wg", "example-hk-01", "203.0.113.10", 51820, "HK", "香港",
     "Hong Kong", true, 42, 98, true],
    [1002, "ovpn", "legacy-hk", "203.0.113.11", 1194, "HK", "香港",
     "Hong Kong", false, 0, 0, false]
  ],
  "cfg": {
    "wg": {
      "address": "10.14.0.2/16",
      "dns": "198.51.100.53",
      "pub": ["<base64 peer public key>"],
      "node": {"1001": 0}
    }
  }
}
```

面板只依赖以下部分，其它顶层字段（`clusters`、`countries`、`series` 等）会被忽略：

| 字段 | 必填 | 说明 |
|---|---|---|
| `meta.cols` | 是 | 列名数组，`nodes` 每行的顺序必须与它一致 |
| `nodes` | 是 | 二维数组；空数组会被判为无效 |
| `cfg.wg` | 是 | WireGuard 元数据对象 |
| `cfg.wg.pub` | 是 | 对端公钥数组（base64 字符串） |
| `cfg.wg.node` | 是 | `{"节点id": pub数组下标}`，key 用字符串 |
| `cfg.wg.address` | 否 | 面板不用于改本机地址，仅兼容原矩阵 |
| `cfg.wg.dns` | 否 | 同上 |

## 3. `meta.cols` 中面板会读取的列

至少应包含：

```text
id, proto, name, ip, port
```

建议同时提供：

```text
cc, countryCn, city, alive, ping, health, allowed
```

解析逻辑：

- `proto != "wg"` 的行直接跳过（OpenVPN 等不导入，面板只切 WireGuard）。
- `id` 用于和 `cfg.wg.node` 的 key 对应；必须是数字或数字字符串。
- `name` 用于节点池去重和面板显示。
- `ip` + `port` 组成 `Endpoint`。
- `alive` 为真时初始状态为 online，否则 offline。
- `ping` 作为初始延迟参考，`health` 作为健康度展示。
- `allowed` 保留原矩阵的允许来源信息，不参与切换。
- 未提供的列使用默认值（`countryCn`/`city` 为 `—`，`alive` 为 false 等），不会导致解析失败。

## 4. `cfg.wg.node` 与 `pub` 的对应

```json
"pub": [
  "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
  "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB="
],
"node": {"1001": 0, "1003": 1}
```

- `node` 的 key 是 `nodes` 行里的 `id`（转成字符串）。
- value 是 `pub` 数组下标；越界或非整数时该节点会被视为不可切换（没有公钥）。
- 没有公钥的节点可以展示，但不能切换。

## 5. 自建数据源的最小返回

只要满足上面的结构，最小的 `data.js` 可以是：

```json
{
  "meta": {"cols": ["id", "proto", "name", "ip", "port", "alive", "ping"]},
  "nodes": [
    [1, "wg", "internal-01", "203.0.113.20", 51820, true, 10]
  ],
  "cfg": {"wg": {"pub": ["<peer-public-key>"], "node": {"1": 0}}}
}
```

## 6. 面板侧的校验与切换

- 「系统设置 → 节点数据源 → 测试并校验」会调用 `POST /api/system/source/test`，
  校验 URL、JSON、`meta.cols`、`nodes`、`cfg.wg.pub/node`、至少一个 `proto=wg` 节点，
  返回总节点数、WG 节点数、可切换节点数。
- 保存时 `PUT /api/system/config` 会再次校验；失败不会写入 `config.json`。
- 保存成功后立即执行一次 `matrix_sync(force=True)` 刷新节点池；如果这次同步失败，
  配置仍保留，后台 6 小时节流/`--sync` 会再试。
- `config.json` 的 `nodeSource` 优先于 systemd 的 `GW_MATRIX_URL`；清空 `nodeSource`
  才会回退到环境变量默认值。
- 「数据源」页的「手动更新」只更新国内 IP/gfwlist；节点池同步用
  `python3 /opt/gw-admin/gw_server.py --sync`，或在「节点数据源」保存一次。

## 7. 安全

- `data.js` 里通常含节点入口 IP 和 WireGuard 公钥（不含私钥），但仍建议只在内网提供。
- 如果地址里带 token，token 会落到 `/opt/gw-admin/data/config.json`，不要提交回仓库。
- 内网源如果跑在 ZeroTier/Tailscale 上，先保证 J1900 已加入并拿到地址；面板启动顺序不必严格，
  同步失败会保留现有节点池，稍后手动 `--sync` 即可。
