# cmake-stm32-autodebug-skill

![platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-blue)
![target](https://img.shields.io/badge/MCU-STM32%20%E5%85%A8%E7%B3%BB%E5%88%97-orange)
![build](https://img.shields.io/badge/build-CMake%20%2B%20Ninja%20%2B%20arm--none--eabi--gcc-informational)
![flash](https://img.shields.io/badge/flash-OpenOCD%20%7C%20pyOCD%20%7C%20STM32CubeProgrammer-success)
![license](https://img.shields.io/badge/license-MIT-green)

**给 AI（也给人）用的 CMake 版 STM32 全自动调试 skill：工具链自动发现 → 编译 → 烧录 → 调试 → 串口闭环验证，结论以退出码为准。**

> 与 Keil 版 [`stm32-autodebug`](https://github.com/zeroangle000) 互补：
> 那个管 `.uvprojx` + UV4，这个管 `CMakePresets + Ninja + arm-none-eabi-gcc`。
> 覆盖 **C0 / F0 / F1 / F2 / F3 / F4 / F7 / G0 / G4 / H5 / H7 / L0 / L1 / L4 / L5 / U0 / U3 / U5 / WB / WBA / WL / XL**，
> 不针对某一颗芯片。

---

## 为什么用它

| 痛点 | 这个 skill 怎么解决 |
|---|---|
| 换电脑后 "`arm-none-eabi-gcc is not a full path`" | **工具链自动发现**：config → `CMSK_*` 环境变量 → PATH → winget/xpack/Arm 安装目录，**零硬编码路径** |
| 不知道缺什么 | `env_doctor.py` 一次体检 6 类：工具+版本门禁 / openocd scripts / 探针 / 串口占用 / 残留进程 / 产物新鲜度，缺什么给什么命令 |
| 烧录失败后瞎改代码 | 烧录失败 = `exit 2`（**硬件问题**），闭环立即中止，不会拿旧固件的串口输出骗自己 |
| "改了代码但行为没变" | 编译前后对比产物 `sha256`，没变化直接 `exit 5`（禁止烧旧产物） |
| AI 只看日志文字就宣布成功 | **判据优先级：退出码 > 串口令牌 > 日志文字**；连续两轮同样失败 → `exit 5` 停机交人工 |
| 只支持一种烧录器 | OpenOCD（全系列，自带 target cfg）/ pyOCD（需 pack）/ STM32CubeProgrammer CLI（低电压更宽容）三选一 |

---

## 30 秒上手

```bash
# 1) 体检：工具链 / 探针 / 串口 / 工程产物（缺什么给什么）
python scripts/env_doctor.py

# 2) 复制配置模板，改成你的工程（preset、产物名、芯片、串口）
cp config/project.example.json config/project.json
#    Windows: copy config\project.example.json config\project.json

# 3) 闭环：编译 → 烧录 → 串口令牌
python scripts/flash_loop.py --project . --config config/project.json
echo $?     # 0=全过  1=编译  2=烧录  4=串口  5=停机  6=环境
```

只想编译、不碰板子：

```bash
python scripts/flash_loop.py --project . --dry-run      # 预检 + 编译 + 打印 sha256
```

---

## 命令一览

| 命令 | 作用 | 退出码 |
|---|---|---|
| `env_doctor.py` | 环境体检（6 类检查） | `0` 齐全 / `6` 缺必需项 |
| `env_doctor.py --json` | 同上，机器可读（给 AI 用） | 同上 |
| `env_doctor.py --install-hints` | 只打印缺项的安装命令（含官网/镜像与"已验证"标记） | 同上 |
| `env_doctor.py --probe-net` | 实测下载源连通性（决定用官方还是国内镜像） | 同上 |
| `env_doctor.py --fix --yes` | 结束残留 `pyocd/openocd` 进程 | 同上 |
| `flash_loop.py` | 编译→烧录→串口 闭环 | `0~6`（见下表） |
| `serial_probe.py --list` | 列出串口 | `0/4` |
| `serial_probe.py --cmd PING --expect "@PONG"` | 文本令牌断言 | `0/4` |
| `serial_probe.py --expect-hex "AA 55"` | **二进制帧头断言**（带 CRC 的私有协议用） | `0/4` |
| `toolresolve.py` | 只列工具与版本 | — |

### 退出码契约

| 码 | 含义 | 该做什么 |
|---|---|---|
| `0` | 编译 + 烧录 + 串口令牌 全过 | 可交付 |
| `1` | 编译/链接失败 | 按报告改源码（GCC 输出天然带 `文件:行:列`） |
| `2` | 烧录失败 | **硬件/环境问题**：USB、供电、接线、驱动，别改业务代码 |
| `3` | 运行时崩溃（HardFault/断言） | 按 PC 反查源码行 |
| `4` | 串口打不开 / 等不到令牌 | 查占用、波特率、令牌字符串 |
| `5` | 连续两轮相同失败 / 无新产物 | **停止盲改**，向人报告卡点 |
| `6` | 环境缺失（工具/探针/串口） | 装环境，重跑 `env_doctor` |

> 闭环里有两条**不可调换**的顺序：
> ① 先 halt → 再开串口 → 最后 resume（否则启动横幅几十毫秒就打完了，表现成"每轮超时"）；
> ② 烧录失败立即中止（否则串口读到的是**上一版固件**的行为）。

---

## 覆盖范围

### 烧录后端

| 后端 | 覆盖 | 依赖 | 默认 |
|---|---|---|---|
| **OpenOCD** | 全部 STM32 系列（自带 `target/stm32*.cfg`，**不用装 pack**） | openocd ≥0.11 | ✅ 主 |
| **pyOCD** | 内置仅 18 个 STM32 target，其余 `pyocd pack install <part>` | pyocd ≥0.34 | 备选 |
| **STM32CubeProgrammer CLI** | 全系列（**对低电压更宽容**，OpenOCD 有硬性电压门槛） | ST 账号下载 | 兜底 |

### 系列 → OpenOCD target（实测自 openocd 0.12.0 的 `scripts/target/`）

```
C0  stm32c0x        F0  stm32f0x        F1  stm32f1x        F2  stm32f2x
F3  stm32f3x        F4  stm32f4x        F7  stm32f7x        G0  stm32g0x
G4  stm32g4x        H7  stm32h7x / stm32h7x_dual_bank       H5  stm32x5x_common
L0  stm32l0 / _dual_bank    L1  stm32l1 / _dual_bank        L4  stm32l4x
L5  stm32l5x        U0  stm32u0x        U3  stm32u3x        U5  stm32u5x
WB  stm32wbx        WBA stm32wbax       WL  stm32wlx        XL  stm32xl
```

完整对照（含 pyOCD target 命名、`-mcpu`/FPU）见 [references/01-toolchain.md](references/01-toolchain.md)。

---

## 实测记录（真机，可复现）

| 项目 | 结果 |
|---|---|
| **STM32F407VE**（CMake + Ninja + GCC 15.2.1） | 编译 `FLASH 54 664 B / 512 KB`；`openocd -f interface/stlink.cfg -f target/stm32f4x.cfg -c "program xxx.elf verify reset exit"` → **Verified OK**（device id `0x10076413`） |
| 同一板串口验证 | `serial_probe.py --expect-hex "AA 55"` → **PASS：20.0 帧/秒，327/327 帧无损**（25 B 帧，头 `AA 55 01 12`，尾 `0D 0A`） |
| **STM32H723VG**（MC02 板） | 工具链发现 7/7；`env_doctor` 缺探针时正确 `exit 6` |
| pyOCD 覆盖范围 | 实测 `stm32f407ve not recognized` → 印证"内置仅 18 个 target"，故 OpenOCD 为主后端 |

⏳ **尚未验证**（见 [07-troubleshooting.md](references/07-troubleshooting.md) 末尾）：H7 的 OpenOCD 烧录、
`open failed` 的驱动归因、`RelWithDebInfo` 下断点单步、CH340 假死的稳定复现条件。

---

## 目录结构

```
SKILL.md                        AI 入口（怎么调用、退出码契约、判据优先级）
README.md                       本文件（人类入口）
references/
  01-toolchain.md               ★ 工具链参照表 + 发现顺序 + 版本门禁 + 全系列对照
  02-install.md                 ★ 安装指引（含国内镜像实测结论 + IDE 提示）
  03-build.md                   CMake 预设、产物、DTCM/RAM 分区坑
  04-flash.md                   OpenOCD / pyOCD / CubeProgrammer、失败分类、系列特例
  05-debug.md                   GDB、DWARF 门禁、断点上限、reset 语义
  06-serial.md                  令牌 + 守恒量断言、顺序要求
  07-troubleshooting.md         16 条实测坑
  08-cubemx-cmake.md            CubeMX+CMake 专题（谁被覆盖、find_program、收源码）
scripts/
  toolresolve.py                工具发现（4 级顺序，可 import）
  env_doctor.py                 环境体检（exit 0/6）
  flash_loop.py                 闭环（exit 0~6）
  serial_probe.py               串口断言（文本/正则/二进制帧头）
config/project.example.json     工程适配模板（复制成 project.json）
```

---

## 常见问题

**Q：必须装 STM32CubeMX 吗？**
不必。纯命令行流程（编译/烧录/串口）不需要它；只有要改 `.ioc`、重新生成 `Core+Drivers`、改引脚时钟时才需要。
`env_doctor` 会把它列为 `[OPT]` 并给官网。

**Q：为什么我的工程里 `.bin` 不生成？**
CubeMX 生成的 `CMakeLists.txt` 默认只产 `.elf`。用 `objcopy` 或加 `POST_BUILD` 步骤，
写法见 [references/08-cubemx-cmake.md](references/08-cubemx-cmake.md) §4。

**Q：CubeMX 重新 Generate 后编译挂了？**
它会把 `cmake/gcc-arm-none-eabi.cmake` **重写**回"依赖 PATH"的版本。
把 `find_program` 版存成模板贴回去，见 [08](references/08-cubemx-cmake.md) §2。

**Q：openocd 报 `Target voltage: 1.0x V` / `init mode failed`？**
先查供电与 VTREF 接线（判断表见 [07](references/07-troubleshooting.md) 第 14 条）；
OpenOCD 有硬性电压门槛，换 STM32CubeProgrammer 往往还能烧（[04](references/04-flash.md) §1.4）。

**Q：Release 下断点不生效？**
`-Os -g0` 没有调试信息。用 `Debug` 或加 `RelWithDebInfo`（`-Os -g3 -gdwarf-4`），
调试前跑一遍 DWARF 门禁（[05](references/05-debug.md) §1）。

---

## 已验证环境（作者本机，供对照）

```
Windows 11 · python 3.12.2 · cmake 4.4.4 · ninja 1.13.0
arm-none-eabi-gcc 15.2.1（xpack）· gdb 16.3.90
openocd 0.12.0-7（winget xpack）· pyocd 0.45.1
```

> 换电脑时不必照抄路径：跑 `env_doctor.py`，它会打印本机实际使用的每一套工具，
> 抄进 `config/project.json` 或环境变量即可。

---

## 贡献

- 发现新坑：直接改 `references/07-troubleshooting.md`，**请标注是否已真机复现**（`✅已复现` / `⏳待验证`）
- 新增系列/芯片：在 `01-toolchain.md` 的对照表补一行，并注明 openocd target cfg 名
- 改脚本：保持"退出码契约"不变（`0/1/2/3/4/5/6`），别把错误码语义换掉

## 许可

[MIT](LICENSE)
