# 01 · 工具链参照表

> 本文件是 **"差什么工具、怎么核对、去哪装"** 的唯一真相。
> 所有路径都不是硬编码——`scripts/toolresolve.py` 按下面的顺序**现场发现**。

---

## 1. 覆盖范围：全系列 STM32

本 skill **不针对某一颗芯片**，适用于所有 Cortex-M 的 STM32：

```
C0  F0  F1  F2  F3  F4  F7  G0  G4  H5  H7
L0  L1  L4  L5  U0  U3  U5  WB  WBA  WL  XL
```

系列差异只体现在**三个名字**上：CMake 工具链文件里的 CPU 参数、OpenOCD 的 `target/*.cfg`、pyOCD 的 target 名。

### 1.1 系列 → OpenOCD target 配置（本机 openocd 0.12.0-7 实测存在）

| 系列 | `target/…cfg` | 备注 |
|---|---|---|
| STM32C0 | `stm32c0x.cfg` | |
| STM32F0 | `stm32f0x.cfg` | |
| STM32F1 | `stm32f1x.cfg` | |
| STM32F2 | `stm32f2x.cfg` | |
| STM32F3 | `stm32f3x.cfg` | |
| STM32F4 | `stm32f4x.cfg` | |
| STM32F7 | `stm32f7x.cfg` | |
| STM32G0 | `stm32g0x.cfg` | |
| STM32G4 | `stm32g4x.cfg` | |
| STM32H5 | `stm32x5x_common.cfg` | 需配合具体 target（openocd 0.12 命名见包内） |
| STM32H7 | `stm32h7x.cfg` / `stm32h7x_dual_bank.cfg` | **双 bank 器件用 dual_bank** |
| STM32L0 | `stm32l0.cfg` / `stm32l0_dual_bank.cfg` | |
| STM32L1 | `stm32l1.cfg` / `stm32l1x_dual_bank.cfg` | |
| STM32L4 | `stm32l4x.cfg` | |
| STM32L5 | `stm32l5x.cfg` | TrustZone：注意 `-c "stm32l5x option_…"` |
| STM32U0 | `stm32u0x.cfg` | |
| STM32U3 | `stm32u3x.cfg` | |
| STM32U5 | `stm32u5x.cfg` | TrustZone |
| STM32WB | `stm32wbx.cfg` | 无线核（CPU2）需先停 |
| STM32WBA | `stm32wbax.cfg` | |
| STM32WL | `stm32wlx.cfg` | |
| STM32XL | `stm32xl.cfg` | |

> 命令查证（不要凭记忆）：`ls <openocd_scripts>/target | grep stm32`
> `env_doctor.py --json` 的 `openocd_scripts` 字段会给出本机 scripts 路径。

### 1.2 系列 → pyOCD target 名（**注意内置只有 18 个**）

pyOCD 0.45.1 内置 STM32 target 实测仅：
`stm32f051 stm32f103rc stm32f412xe stm32f412xg stm32f429xg stm32f429xi stm32f439xg stm32f439xi stm32f767zi stm32h723xx stm32h743xx stm32h750xx stm32h7b0xx stm32l031x6 stm32l432kc stm32l475xc stm32l475xe stm32l475xg`

其它型号要先装 CMSIS-Pack：

```bash
pyocd pack install stm32g4          # 按系列
pyocd pack install stm32g431rb      # 或按具体型号
pyocd list --targets | grep -i stm32   # 装完核对
```

命名规则一般是：`stm32` + 系列 + 引脚数/Flash 代号，全小写（`stm32f407vg`、`stm32g431rb`、`stm32u575xx`）。

> ⚠️ 结论：**要覆盖全系列，优先用 OpenOCD**；pyOCD 适合内置列表里的型号或能装 pack 的环境。

### 1.3 系列 → CMake 工具链参数

在 `cmake/gcc-arm-none-eabi.cmake`（或 CubeMX 生成的同类文件）里通常长这样：

```cmake
set(CPU   "cortex-m7")                 # m0/m0plus/m3/m4/m7/m33
set(FPU   "fpv5-d16")                  # 无 FPU 就别写，或用 soft
set(ARCH  "armv7e-m+fp.dp")            # 与 CPU/FPU 配套
set(ABI   "aapcs")
```

| 系列 | 常见 `-mcpu` | FPU |
|---|---|---|
| C0/F0/L0/G0 | `cortex-m0plus` | 无 |
| F1/F2/L1 | `cortex-m3` | 无 |
| F3/L4/G4 | `cortex-m4` | `fpv4-sp-d16` |
| F4/F7 | `cortex-m4` / `cortex-m7` | `fpv4-sp-d16` / `fpv5-d16` |
| H5/U5/L5 | `cortex-m33` | `fpv5-sp-d16`（可选 DSP） |
| H7 | `cortex-m7` | `fpv5-d16` |

> 这些写在**工程的**工具链文件里，不属于本 skill；本 skill 只要求"能用 CMake 编出 `.elf`"。

---

## 2. 必需 / 可选工具

| 工具 | 必需性 | 用途 | 版本门禁 | 检测方式 |
|---|---|---|---|---|
| **arm-none-eabi-gcc** | 🔴 必需 | 编译/链接 | **≥10.3** | `-dumpversion` |
| **cmake** | 🔴 必需 | 构建驱动 | **≥3.20** | `--version` |
| **python** | 🔴 必需 | 本 skill 脚本 | **≥3.8** | `-V` |
| **arm-none-eabi-gdb** | 🟠 调试需要 | 断点/回溯 | ≥10 | `--version` |
| **ninja** | 🟠 推荐 | 生成器（可退回 Make） | ≥1.10 | `--version` |
| **openocd** | 🟠 烧录主后端 | 全系列烧录/调试 | ≥0.11 | `--version` |
| **pyocd** | 🟠 备选后端 | 烧录/调试 | ≥0.34 | `--version` |
| **pyserial** | 🔴 串口需要 | 串口断言 | 任意 | `python -c "import serial"` |

版本不达标时 `env_doctor` 报 `BAD`（不是 `MISS`），并保留路径与实测版本，方便判断要不要升级。

---

## 3. 发现顺序（`scripts/toolresolve.py`）

```
① config/project.json → paths.<tool>            （显式，最高优先）
② 环境变量            → CMSK_GCC / CMSK_GDB / CMSK_CMAKE / CMSK_NINJA
                        CMSK_PYTHON / CMSK_PYOCD / CMSK_OPENOCD
③ PATH                → shutil.which
④ 常见安装位置（glob）：
   Windows:
     %LOCALAPPDATA%\Microsoft\WinGet\Packages\*\**\bin      ← winget/xpack 安装的 openocd 在这里
     %LOCALAPPDATA%\Microsoft\WinGet\Links
     %LOCALAPPDATA%\Programs\*\**\bin
     %USERPROFILE%\.xpack\**\bin
     C:\xpack*\**\bin
     C:\Program Files\Arm GNU Toolchain arm-none-eabi\**\bin
     C:\Program Files (x86)\Arm GNU Toolchain arm-none-eabi\**\bin
     D:\toolchains\**\bin , C:\toolchains\**\bin , %USERPROFILE%\toolchains\**\bin
   Linux / macOS:
     /opt/**/bin , /usr/local/**/bin , /usr/bin , /usr/local/bin
     ~/.local/bin , ~/.xpack/**/bin , /opt/homebrew/bin , /usr/local/opt/**/bin
⑤ 都没有 → MISSING + 安装命令
```

**为什么用 glob 而不是固定路径**：winget 的包目录带哈希后缀（例如
`…\WinGet\Packages\xpack-dev-tools.openocd-xpack_Microsoft.Winget.Source_8wekyb3d8bbwe\xpack-openocd-0.12.0-7\bin`），
写死必挂。

### OpenOCD scripts 目录定位

顺序：`config.paths.openocd_scripts` → `<openocd 包根>/openocd/scripts` →
`<包根>/share/openocd/scripts` → `<包根>/scripts` →
`/usr/share/openocd/scripts` → `/usr/local/share/openocd/scripts` → Homebrew 前缀。

判据：该目录下存在 `target/`（说明是真正的 scripts 根）。

---

## 4. 自查命令（贴给 AI 或自己核对）

```bash
# 全量体检
python scripts/env_doctor.py
# 机器可读
python scripts/env_doctor.py --json
# 只列工具
python scripts/toolresolve.py
# 缺什么、装什么（含镜像与验证状态）
python scripts/env_doctor.py --install-hints
# 实测下载源连通性（决定用官方还是国内镜像）
python scripts/env_doctor.py --probe-net
```

期望：`工具 7/7 OK` + `openocd scripts OK` + `探针 OK` + `串口空闲` → exit 0。

---

## 5. 常见"差什么"对照

| 体检结果 | 缺的是 | 装它（详见 02-install.md） |
|---|---|---|
| `MISS ARM GCC` | 编译器 | ARM 官方安装包 / `winget install -e --id xpack-dev-tools.arm-none-eabi-gcc` |
| `BAD CMake 版本过低` | cmake <3.20 | `python -m pip install -U cmake -i <清华源>` |
| `MISS pyOCD / python 脚本报 ModuleNotFound` | pyocd/pyserial | `python -m pip install pyocd pyserial -i <清华源>` |
| `MISS OpenOCD` | 烧录后端 | `winget install -e --id xpack-dev-tools.openocd-xpack` |
| `WARN openocd scripts 定位不到` | 包不完整/自定义安装 | 设 `CMSK_OPENOCD` 或 `config.paths.openocd_scripts` |
| `MISS 探针` | ST-Link 未插/驱动异常 | 见 07-troubleshooting #2/#3 |
| `WARN 串口被占用` | 上位机/串口助手没关 | 关掉后重跑 |
| `产物比源码旧` | 没重新编译 | `cmake --build --preset <P>` |
