# 06 · 串口验证（令牌 + 守恒量断言）

> 串口是"固件到底跑没跑起来"的最便宜证据。判据不要写"看到 OK 就算过"——
> 日志里可能混着上一轮输出，必须用**唯一令牌**或**守恒量**。

---

## 1. 参数

| 项 | 常见值 | 说明 |
|---|---|---|
| 波特率 | 115200 / 921600 | 以工程实际为准 |
| 帧格式 | 8N1 | 少数外设用 8E2（如 SBUS 是 100000 8E2） |
| 行尾 | `\r\n` | 本 skill 默认发 CRLF |
| 端口 | `COMx`（Windows）/ `/dev/ttyUSBx`（Linux） | `env_doctor` 会列出来 |

USB 转串口芯片（CH340/CP210x/FT232）在大电流负载下可能**假死**：
表现为"之前好好的，电机一转就收不到数据"。对策见 07-troubleshooting #5。

---

## 2. 两种断言

### 2.1 令牌断言（最常用）

```bash
python scripts/serial_probe.py --port COM14 --baud 115200 \
       --cmd PING --expect "@PONG" --timeout 3
```

- 退出码 0 = 收到匹配；4 = 超时/打不开（对应 skill 的 exit 4）
- 支持正则：`--expect "@PONG|@ERR 10"`、`--expect-re`

### 2.2 守恒量断言（更强，能发现"部分丢字节"）

以"字节守恒"为例（本项目 `@RX` 的输出）：

```
@RX total=<fed> idle=<n> ht=<n> tc=<n> wrap=<n> late=<n> err=<n> pos=<rpos> ovf=<n> acc=<n> cons=<n> pend=<n>
```

判定：

```
① total == acc == cons        （进了多少字节、解析了多少字节要对上）
② ovf == 0                    （接收环没有溢出）
③ late == 0                   （服务没有被拖住）
④ pend 很小                    （没有积压）
```

```bash
python scripts/serial_probe.py --port COM14 --cmd "@RX" --expect-re \
  "total=(\\d+).*ovf=0.*acc=\\1.*cons=\\1.*pend=0"
```

> ⚠️ 正则分组回引（`\1`）依赖具体实现；若你的固件格式不同，
> 用 `--read-seconds 2` 把原始输出抓回来自己判，比硬套正则可靠。

---

## 3. 与烧录的顺序（★ 不能反）

```
① reset halt（内核停住）   ← 此时不会打印启动横幅
② 打开串口
③ resume / go
④ 等令牌
```

反过来（先 go 再开串口）会漏掉启动横幅，表现为"每轮都超时，但代码其实是好的"。

---

## 4. 常见故障对照

| 现象 | 根因 | 处理 |
|---|---|---|
| `could not open port` / `PermissionError` | 上位机/串口助手占着 | 关掉占用程序；`env_doctor` 的 `serial.busy` 会标出来 |
| 一个字节都收不到 | 接线（TX/RX 反接）、波特率、串口重定向（`printf` 没走这个口） | 先用**已知能输出的**命令（如 `PING`）验链路 |
| 收到乱码 | 波特率/时钟不对（HSE 未起时用 HSI，波特率会偏） | 查时钟树与 USART 分频 |
| 偶发丢字符 | 阻塞式 `printf` + 大电流干扰 | 改非阻塞发送（环形缓冲 + DMA） |
| 电机一转就断 | USB 转串口假死 | 拔插、换口、缩短线、加磁环；DTR 复位 |
| 命令发出无回显 | 固件在中断里被更高优先级任务饿死 | 查中断优先级与 ISR 里是否阻塞 |

---

## 5. 给 AI 的调用建议

```bash
# 只读一条状态
python scripts/serial_probe.py --port COM14 --cmd "STAT 1" --read-seconds 0.5

# 关键回归：令牌 + 守恒量
python scripts/serial_probe.py --port COM14 --cmd PING --expect "@PONG"
python scripts/serial_probe.py --port COM14 --cmd "@RX" --read-seconds 0.5 --expect "ovf=0"
```

**不要**用"串口有没有输出"当唯一判据：要做**内容断言**，否则一个只会打印 banner 的死固件也能骗过测试。
