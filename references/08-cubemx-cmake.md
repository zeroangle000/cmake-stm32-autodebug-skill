# 08 · CubeMX + CMake 工程专题（F407 实战整理）

> 面向 **CubeMX 生成 → CMake + arm-none-eabi-gcc 编译 → ST-LINK 烧录** 的工程。
> 内容来自一次真实工程（STM32F407VET6 遥控器）的配置记录，坑都是踩过的。

---

## 1. 谁会被 CubeMX 覆盖（必须先背下来）

| 路径 | CubeMX `Generate Code` 时 | 应对 |
|---|---|---|
| `Core/**` | **重写**（只保留 `/* USER CODE BEGIN */` 段） | 用户代码只能写在 USER CODE 段内 |
| `Drivers/**` | **重写** | 不要手改 |
| `cmake/stm32cubemx/CMakeLists.txt` | **重写** | 不要手改 |
| **`cmake/gcc-arm-none-eabi.cmake`** | ⚠️ **重写** | **每次 Generate 后都要重新改成"硬编码/绝对路径"版** |
| `CMakeLists.txt`（顶层） | 不覆盖（*generated only once*） | 收录业务源码、加 include 都在这里 |
| `Firmware/**`（自建业务目录） | **完全不管** | 业务代码放这里最安全 |
| `CMakePresets.json` | 一般不覆盖 | 可加自定义预设 |

> 结论：**把业务代码放到 `Core/` 和 `Drivers/` 之外**（如 `Firmware/`），
> 只把 USER CODE 段留给 CubeMX。

---

## 2. 工具链文件：为什么要改（★核心）

CubeMX 默认生成的 `cmake/gcc-arm-none-eabi.cmake` 是这样的：

```cmake
# arm-none-eabi- must be part of path environment
set(TOOLCHAIN_PREFIX   arm-none-eabi-)
set(CMAKE_C_COMPILER   ${TOOLCHAIN_PREFIX}gcc)
```

问题：`arm-none-eabi-gcc` 只是裸名字，CMake 去 `PATH` 里找。**IDE（CLion / VS Code）拉起的 CMake 进程通常没有这个 PATH**，于是：

```
The CMAKE_C_COMPILER: arm-none-eabi-gcc is not a full path and was not found in the PATH.
```

### 正确改法：`find_program` + 可覆盖的目录变量

```cmake
# 工具链走 find_program，不依赖 PATH：换 shell / 换 IDE 都能找到编译器。
# 想换版本：改 XPACK_GCC_BIN，或 cmake -DXPACK_GCC_BIN=...
#
# ★ 为什么不直接写绝对路径：
#   本文件开头 CMAKE_SYSTEM_NAME=Generic，CMake 会把 CMAKE_EXECUTABLE_SUFFIX 置空，
#   写 ".../arm-none-eabi-gcc" 时不会自动补 .exe → 报 "is not a full path to an
#   existing compiler tool"。
#   find_program 会按主机规则补 .exe，且 HINTS 优先指向指定目录，最可靠。
set(XPACK_GCC_BIN "D:/toolchains/xpack-arm-none-eabi-gcc-15.2.1-1.1/bin"
    CACHE PATH "GNU Arm Embedded GCC bin directory")

find_program(ARM_GCC_EXE     NAMES arm-none-eabi-gcc     HINTS "${XPACK_GCC_BIN}" REQUIRED)
find_program(ARM_GXX_EXE     NAMES arm-none-eabi-g++     HINTS "${XPACK_GCC_BIN}" REQUIRED)
find_program(ARM_OBJCOPY_EXE NAMES arm-none-eabi-objcopy HINTS "${XPACK_GCC_BIN}" REQUIRED)
find_program(ARM_SIZE_EXE    NAMES arm-none-eabi-size    HINTS "${XPACK_GCC_BIN}" REQUIRED)

set(CMAKE_C_COMPILER   "${ARM_GCC_EXE}")
set(CMAKE_ASM_COMPILER "${ARM_GCC_EXE}")
set(CMAKE_CXX_COMPILER "${ARM_GXX_EXE}")
set(CMAKE_LINKER       "${ARM_GXX_EXE}")
set(CMAKE_OBJCOPY      "${ARM_OBJCOPY_EXE}")
set(CMAKE_SIZE         "${ARM_SIZE_EXE}")
set(TOOLCHAIN_PREFIX   "${XPACK_GCC_BIN}/arm-none-eabi-")
```

> **不要写死某一台机器的路径**：给别人用时，让对方改 `XPACK_GCC_BIN` 或
> `cmake -DXPACK_GCC_BIN=<自己的 bin> --preset Debug`。
> 本 skill 的 `env_doctor.py` 会自动找到 gcc 并打印路径，抄进这里即可。

---

## 3. 顶层 `CMakeLists.txt`：收录业务源码

CubeMX 只收 `Core/Src` + HAL 驱动。自建目录（如 `Firmware/`）**一个文件都不会进构建**，
于是 `main.c` 里 `#include "app_main.h"` 会直接 `undefined reference`。

```cmake
# Add sources to executable
# 自建业务目录 CubeMX 不纳入，必须手工收录；新增 .c 时在这里追加
target_sources(${CMAKE_PROJECT_NAME} PRIVATE
    Firmware/App/app_main.c
    Firmware/App/app_ui.c
    Firmware/Service/sys_blackboard.c
    Firmware/Service/sys_scheduler.c
    Firmware/Service/proto_telemetry.c
    Firmware/BSP/bsp_adc.c
    Firmware/BSP/bsp_gpio.c
    Firmware/BSP/bsp_spi.c
    Firmware/BSP/bsp_tim.c
    Firmware/BSP/bsp_uart.c
    Firmware/Module/joystick.c
    Firmware/Module/key_matrix.c
    Firmware/Module/power_mp2672.c
    Firmware/Module/st7789.c
)

# Add include paths
target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE
    Firmware/App
    Firmware/Service
    Firmware/BSP
    Firmware/Module
)
```

> 顶层 `CMakeLists.txt` 只生成一次，**新增源文件记得回来加**（否则症状是 `undefined reference`）。

---

## 4. `.bin` / `.hex`：CubeMX 默认不生成

```bash
arm-none-eabi-objcopy -O binary build/Debug/xxx.elf build/Debug/xxx.bin
arm-none-eabi-objcopy -O ihex   build/Debug/xxx.elf build/Debug/xxx.hex
```

建议做成 CMake 的 `add_custom_command(TARGET ... POST_BUILD ...)`，否则
"编译成功但 `build/` 里没有 `.bin`" 会反复发生（本 skill 的 `flash_loop` 有新鲜度检查，
产物不存在会直接 `exit 6`）。

---

## 5. IDE 设置（两个高频坑）

### CLion

| 坑 | 现象 | 解决 |
|---|---|---|
| 打开的目录层级错了 | 工具栏没有 🔨 编译按钮 | 要打开**含 `CMakeLists.txt` 的那一层**（不是父目录） |
| 运行配置指错产物 | `error=193 不是有效的 Win32 应用程序` | Run/Debug 指向 `.elf` 且用 OpenOCD/GDB 远程，**不要直接 Run 可执行文件** |
| `cmake.sourceDirectory` 指向不存在路径 | CMake 配置失败 | Settings → Build → CMake → 选对 `CMakeLists.txt` |

### VS Code

| 坑 | 现象 | 解决 |
|---|---|---|
| CMake Tools 找不到编译器 | 同 §2 的 PATH 报错 | 用改过的 toolchain 文件（§2） |
| ESP-IDF 扩展抢设备 | 报 `esp_usb_jtag: could not find or open device`，整条任务链标红 | `.vscode/settings.json` 里 `"idf.openOcdConfigs": []` |

---

## 6. 一键脚本（放工程根目录，可选）

```bat
:: build.bat —— 只编译
@echo off
cmake --preset Debug && cmake --build --preset Debug
```

```bat
:: flash.bat —— 只烧录（openocd）
@echo off
openocd -f interface/stlink.cfg -f target/stm32f4x.cfg ^
  -c "program build/Debug/xxx.elf verify reset exit"
```

```bat
:: rebuild.bat —— 改了 CMakeLists / 工具链文件后用
@echo off
rmdir /s /q build\Debug
cmake --preset Debug && cmake --build --preset Debug
```

> 本 skill 的 `flash_loop.py` 已经把"编译 → 新鲜度 → 烧录 → 串口"串起来，
> 比 bat 多了退出码与失败分类；bat 适合不想装 python 的机器。

---

## 7. 换电脑 / 换工具链版本

```
1) python scripts/env_doctor.py            # 看缺什么、装什么（含可选 IDE）
2) 把 env_doctor 打印的 gcc 路径填进 cmake/gcc-arm-none-eabi.cmake 的 XPACK_GCC_BIN
   （或 cmake -DXPACK_GCC_BIN=... --preset Debug，不改文件）
3) python scripts/env_doctor.py            # 复测 → exit 0
4) 改过 CMakeLists / 工具链文件 → 删 build/<Preset> 重新配置（见 rebuild.bat）
```

**同一台机器上可能有多套 GCC**（例如 VS Code 的 STM32 扩展会自己下 `gnu-tools-for-stm32`）。
**不要混用**：工具链文件里只认一个 `XPACK_GCC_BIN`，`env_doctor` 也会显示它实际用的是哪一套。
