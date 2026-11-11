---
name: cmake-stm32-autodebug-skill
description: 在 CMake + GCC 的 STM32 工程上做"编译→烧录→调试→串口验证"闭环。用于改完固件要上板验证、板子只打印不动作/死机要定位、或换电脑后要先查工具链缺什么。支持工具链自动发现（不绑死路径）、OpenOCD/pyOCD 双烧录后端、GDB 源码级调试、串口令牌断言。仅限 STM32 / Cortex-M。
---

# CMake STM32 全自动调试

给 AI 补上"改完代码到底跑没跑起来"的反馈回路：工具链体检 → 编译并解析错误行号 → 烧录（openocd 主 / pyocd 备）→ 串口令牌验证 → 失败归因到源码。

> 与 `stm32-autodebug`（Keil MDK 专用）互补：那个管 `.uvprojx`，这个管 **CMakePresets + Ninja + arm-none-eabi-gcc**。

---

## 0. 第一步永远是体检（不要跳）

```bash
python scripts/env_doctor.py            # 人读
python scripts/env_doctor.py --json     # 机器读（AI 用这个）
python scripts/env_doctor.py --install-hints   # 只打印缺项的安装命令
python scripts/env_doctor.py --probe-net       # 额外实测下载源连通性
```

退出码 **0 = 齐全**；**6 = 缺工具/探针/串口**。**不要**在 exit 6 时继续烧录——先按提示装。

体检 6 类：工具链+版本门禁 / openocd scripts 目录 / 调试探针 / 串口占用 / 残留 pyocd·openocd 进程 / 工程产物是否比源码新。

---

## 1. 工具链怎么找（不要写死路径）

`scripts/toolresolve.py` 的发现顺序：

```
1 config/project.json 的 paths.<tool>     ← 显式优先
2 环境变量 CMSK_GCC / CMSK_GDB / CMSK_OPENOCD / CMSK_PYOCD / CMSK_CMAKE / CMSK_NINJA / CMSK_PYTHON
3 PATH（shutil.which）
4 常见安装位置（Windows: winget Packages、%USERPROFILE%\.xpack、C:\xpack*、
   Program Files\Arm GNU Toolchain、D:/toolchains；Linux/macOS: /opt、/usr/local、
   Homebrew、~/.local/bin）
5 都没有 → 报 MISSING + 安装命令
```

**换电脑时正确做法**：跑一次 `env_doctor.py`，按它给的命令装，**不要改脚本里的路径**。
版本门禁：gcc ≥10.3、cmake ≥3.20、python ≥3.8、pyocd ≥0.34、openocd ≥0.11。

细节与"各工具去哪下（含国内镜像实测结论）"见
[references/01-toolchain.md](references/01-toolchain.md)、[references/02-install.md](references/02-install.md)。

---

## 2. 四条路径

| 目的 | 命令 | 文档 |
|---|---|---|
| 编译 | `cmake --preset <P>` → `cmake --build --preset <P>` | [03-build.md](references/03-build.md) |
| 烧录 | openocd：`-f interface/stlink.cfg -f target/stm32h7x.cfg -c "program <elf> verify reset exit"`；备选 `pyocd flash -t <chip>` | [04-flash.md](references/04-flash.md) |
| 调试 | `openocd … -c "gdb_port 3333"` + `arm-none-eabi-gdb -ex "target extended-remote :3333"`（或 `pyocd gdbserver`） | [05-debug.md](references/05-debug.md) |
| 串口 | `python scripts/serial_probe.py --cmd PING --expect @PONG` | [06-serial.md](references/06-serial.md) |

**调试必须先过 DWARF 门禁**：Release 常带 `-Os -g0`（没有调试信息），源码级调试要用 `Debug` 或 `RelWithDebInfo` 预设。

---

## 3. 闭环脚本与退出码

```bash
python scripts/flash_loop.py --project . --config config/project.json
```

```
① 编译                失败 → exit 1（输出 文件:行:列: error）
② 产物新鲜度（sha256） 没变化 → exit 5（禁止烧旧产物）
③ env_doctor 预检      缺工具/探针/串口 → exit 6
④ reset halt          失败 → exit 2
⑤ flash + verify      失败 → exit 2   ★ 硬件问题，别改代码
⑥ 打开串口            失败 → exit 4
⑦ resume (go)
⑧ 等令牌 @PONG        超时 → exit 4
⑨ 失败签名去重        与上轮相同 → exit 5（停机，交人工）
```

| 退出码 | 含义 | 该做什么 |
|---|---|---|
| 0 | 编译+烧录+串口令牌全过 | 可以交付 |
| 1 | 编译/链接失败 | 按报告改源码 |
| 2 | 烧录失败 | **不是代码问题**：查 USB/供电/接线/驱动 |
| 3 | 运行时崩溃（HardFault/断言） | 按 PC 反查源码行 |
| 4 | 串口打不开 / 等不到令牌 | 查串口占用、波特率、令牌字符串 |
| 5 | 连续两轮相同失败 / 无新产物 | **停止盲改**，向用户报告卡点 |
| 6 | 环境缺失（工具/探针） | 装环境，跑 env_doctor |

**两条硬顺序**（写死，不能换）：

1. **先 halt → 再开串口 → 最后 go**。否则固件启动横幅几十毫秒就打完，串口才刚打开 → 表现为"每轮超时"而代码其实是好的。
2. **烧录失败必须立即中止**。否则串口读到的是**上一版固件**的行为，报告会把后续修改引向完全错误的方向。

---

## 4. 判据优先级

```
退出码 > 串口令牌 > 日志文字
```

**禁止**凭日志里出现 "OK"/"success" 判断成功——日志可能混着上一轮输出。
串口验证除了令牌，还应对照业务守恒量（本项目的 `@RX total=acc=cons, ovf=0, late=0, pend=0`）。

---

## 5. 出问题先看这张表

| 现象 | 先查 |
|---|---|
| `Memory transfer fault (write) @ 0x2000xxxx` | pyOCD flash 算法写 DTCM 失败 → 换 openocd 后端；查 USB/供电 |
| openocd `Error: open failed` | 探针没枚举/驱动不是 WinUSB；先 `pyocd list` 对比 |
| `could not open port COMn: PermissionError` | 串口被上位机/串口助手占用 |
| 发命令没反应但之前正常 | CH340 假死；DTR 复位或拔插 |
| 烧完行为没变 | 烧到了旧产物 / 编译被跳过（看 ② 新鲜度） |
| Release 断点无效 | `-Os -g0`，换 `Debug`/`RelWithDebInfo` |

完整 12 条见 [references/07-troubleshooting.md](references/07-troubleshooting.md)。

---

## 6. 文件导航

```
SKILL.md                    本文件（怎么调用）
README.md                   给人看的快速开始
references/01-toolchain.md  工具链参照表 + 发现顺序 + 版本门禁
references/02-install.md    安装指引（含国内镜像实测结论）
references/03-build.md      CMake 预设、产物、常见链接错误
references/04-flash.md      openocd / pyocd 烧录与失败分类
references/05-debug.md      gdb、DWARF 门禁、断点、reset 语义
references/06-serial.md     串口参数、令牌、守恒量断言
references/07-troubleshooting.md  16 条实测坑
references/08-cubemx-cmake.md     CubeMX+CMake 专题（谁被覆盖 / find_program / 收源码）
scripts/toolresolve.py      工具发现（可 import）
scripts/env_doctor.py       环境体检（exit 0/6）
scripts/flash_loop.py       编译→烧录→串口 闭环（exit 0~6）
scripts/serial_probe.py     串口发命令/断言
config/project.example.json 工程适配模板
```

---

## 7. 改配置而不是改脚本

把 `config/project.example.json` 复制成 `config/project.json`（已 `.gitignore`），改你的 preset 名、产物名、芯片、串口。
**不要**把本机路径写进脚本或 `references/`——那是别人 fork 后第一个踩的坑。
