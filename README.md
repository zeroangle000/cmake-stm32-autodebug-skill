# cmake-stm32-autodebug-skill

给 AI（或人）用的 **CMake + GCC 版 STM32 全自动调试 skill**：
**工具链自动发现 → 编译 → 烧录 → 调试 → 串口闭环验证**，结论以**退出码**为准。

> 与 Keil 版（`stm32-autodebug`）互补：那个管 `.uvprojx`，这个管 `CMakePresets + Ninja + arm-none-eabi-gcc`。
> **适用范围是全系列 STM32**（C0/F0/F1/F2/F3/F4/F7/G0/G4/H5/H7/L0/L1/L4/L5/U0/U3/U5/WB/WBA/WL/XL），
> 不是只针对 H7 —— 见 [references/01-toolchain.md](references/01-toolchain.md) 的系列对照表。

---

## 快速开始（3 步）

```bash
# 1) 体检：工具链/探针/串口/工程产物 一次查清（缺什么会直接给安装命令）
python scripts/env_doctor.py

# 2) 复制配置模板，改成你的工程（preset 名、产物名、芯片、串口）
cp config/project.example.json config/project.json

# 3) 闭环：编译 → 烧录 → 串口令牌
python scripts/flash_loop.py --project . --config config/project.json
```

退出码：`0` 全过 / `1` 编译 / `2` 烧录(硬件) / `3` 运行时崩溃 / `4` 串口 / `5` 停机 / `6` 环境。

---

## 为什么能"换电脑直接用"

**没有任何路径被写死。** 工具按 4 级顺序自动找：

```
config/project.json 的 paths.*  →  环境变量 CMSK_*  →  PATH  →  常见安装位置
```

覆盖范围包括 winget/xpack 包目录、`%USERPROFILE%\.xpack`、`C:\xpack*`、
`Program Files\Arm GNU Toolchain*`、`D:/toolchains`、`/opt`、`/usr/local`、Homebrew、`~/.local/bin`。

找不到就报 `MISSING` 并给出**安装命令 + 官网地址**，每条都标注了「已验证 / 部分 / 未验证」。

---

## 支持的烧录后端

| 后端 | 覆盖 | 依赖 | 默认 |
|---|---|---|---|
| **OpenOCD** | 全部 STM32 系列（自带 `target/stm32*.cfg`，**不需要装 pack**） | openocd ≥0.11 | ✅ 主 |
| **pyOCD** | 内置只有 18 个 STM32 target，其余需 `pyocd pack install <part>` | pyocd ≥0.34 | 备选 |

> 这也是把 OpenOCD 设为主后端的原因：**系列覆盖更全、无 pack 下载依赖**（国内网络更友好）。

---

## 目录

```
SKILL.md                        AI 入口（怎么调用、退出码契约）
README.md                       本文件（人类入口）
references/01-toolchain.md      ★ 工具链参照表 + 发现顺序 + 版本门禁
references/02-install.md        ★ 安装指引（含国内镜像实测结论）
references/03-build.md          CMake 预设、产物、常见链接错误
references/04-flash.md          openocd / pyocd 烧录矩阵与失败分类
references/05-debug.md          gdb、DWARF 门禁、断点、reset 语义
references/06-serial.md         串口参数、令牌、守恒量断言
references/07-troubleshooting.md 16 条实测坑
references/08-cubemx-cmake.md    CubeMX+CMake 专题（谁会被 CubeMX 覆盖、find_program、收源码）
scripts/toolresolve.py          工具发现（可 import）
scripts/env_doctor.py           环境体检（exit 0/6）
scripts/flash_loop.py           编译→烧录→串口 闭环（exit 0~6）
scripts/serial_probe.py         串口发命令/断言
config/project.example.json     工程适配模板
```

---

## 已验证环境（作者本机，供对照）

```
Windows 11 · python 3.12.2 · cmake 4.4.4 · ninja 1.13.0
arm-none-eabi-gcc 15.2.1（xpack）· gdb 16.3.90
openocd 0.12.0-7（winget xpack）· pyocd 0.45.1
STM32H723VGT6 + ST-Link（探针驱动/烧录链路的部分场景仍在验证）
```

> ⏳ 标注：**H7 实机烧录闭环**在作者环境下曾遇到 pyOCD `Memory transfer fault @ DTCM`，
> 因此把 OpenOCD 设为主后端；具体结论见 [07-troubleshooting.md](references/07-troubleshooting.md)。

---

## 实测记录（真机，可复现）

| 项目 | 结果 |
|---|---|
| **STM32F407VE**（`Arm GNU GCC` + Ninja + CMake） | 编译 `FLASH 54 664 B / 512 KB`；`openocd -f interface/stlink.cfg -f target/stm32f4x.cfg -c "program xxx.elf verify reset exit"` → **Verified OK**（device id `0x10076413`） |
| 同一板的串口验证 | `serial_probe.py --expect-hex "AA 55"` → **PASS，20.0 帧/秒，327/327 帧无损**（25 B 帧，头 `AA 55 01 12`，尾 `0D 0A`） |
| **STM32H723VG**（同 skill 的 CMake 工程） | 工具链发现 7/7；`env_doctor` 在缺探针时正确 `exit 6` |
| pyOCD 覆盖范围 | 实测 `stm32f407ve not recognized` → 印证"内置仅 18 个 target，需 `pyocd pack install`"，故 OpenOCD 设为主后端 |

> 这些是**已跑通**的路径；`07-troubleshooting.md` 末尾的 ⏳ 项仍未验证，请勿当成结论。

---

## 许可

MIT（见 [LICENSE](LICENSE)）
