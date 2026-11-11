# 04 · 烧录（OpenOCD 主 / pyOCD 备，全系列 STM32）

> 结论先给：**OpenOCD 是主后端**，因为它的 `target/stm32*.cfg` 覆盖全系列且**不需要下载 CMSIS-Pack**；
> pyOCD 内置只有 18 个 STM32 target，其余要先 `pyocd pack install`。

---

## 1. OpenOCD 通用命令

```bash
openocd -s "<openocd_scripts>" \
        -f interface/stlink.cfg \
        -f target/<系列>.cfg \
        -c "program <你的.elf> verify reset exit"
```

- `-s` = scripts 根目录（`env_doctor.py --json` 的 `openocd_scripts` 字段能拿到）
- `-f interface/…`：ST-Link 用 `stlink.cfg`；J-Link 用 `jlink.cfg`；DAPLink 用 `cmsis-dap.cfg`
- `-f target/…`：按系列选，见下表
- `program <elf>` 直接传 ELF 最省事（地址从 ELF 里来）；传 `.bin` 要加 `0x08000000`

### 1.1 target 配置对照（按系列）

| 系列 | `-f target/…` |
|---|---|
| C0 | `stm32c0x.cfg` |
| F0 / F1 / F2 / F3 | `stm32f0x.cfg` / `stm32f1x.cfg` / `stm32f2x.cfg` / `stm32f3x.cfg` |
| F4 / F7 | `stm32f4x.cfg` / `stm32f7x.cfg` |
| G0 / G4 | `stm32g0x.cfg` / `stm32g4x.cfg` |
| **H7** | `stm32h7x.cfg`（单 bank）/ `stm32h7x_dual_bank.cfg`（双 bank 器件） |
| L0 / L1 | `stm32l0.cfg` / `stm32l1.cfg`（双 bank：`*_dual_bank.cfg`） |
| L4 / L5 | `stm32l4x.cfg` / `stm32l5x.cfg` |
| U0 / U3 / U5 | `stm32u0x.cfg` / `stm32u3x.cfg` / `stm32u5x.cfg` |
| WB / WBA / WL | `stm32wbx.cfg` / `stm32wbax.cfg` / `stm32wlx.cfg` |
| XL | `stm32xl.cfg` |

> 以**本机 ls 结果**为准：`ls "<openocd_scripts>/target" | grep stm32`

### 1.2 系列特例（必看）

| 场景 | 处理 |
|---|---|
| **H7 双 bank**（H743/H750/H723 部分型号、H7B0…） | 用 `stm32h7x_dual_bank.cfg`；否则烧写到一半报 bank 相关错误 |
| **L5 / U5（TrustZone）** | 需决定 `TZEN`；已开 TrustZone 的板子非安全区烧录要 `-c "stm32l5x option_…"` 或用安全调试 |
| **WB / WBA（双核）** | 先停 CPU2（无线核）再烧，否则 flash 被占用 |
| **H7/L4+ 外部 QSPI/OSPI Flash** | OpenOCD 需要额外的 `-f` 外部 loader 配置，否则只能烧内部 flash |
| **读保护 RDP / 写保护 WRP** | 先解除保护（`-c "stm32h7x unlock 0"` 之类），生产环境请勿随意改 option bytes |

### 1.3 连不上探针时

```bash
# 复位后连接（等价于 pyocd 的 under-reset）
openocd ... -c "reset_config srst_only srst_nogate connect_assert_srst" ...
# 降低 SWD 速度（长线/干扰）
openocd ... -c "adapter speed 1000" ...
```

---

### 1.4 备选：STM32CubeProgrammer CLI（对低电压更宽容）

OpenOCD 有**硬性电压门槛**：`Target voltage` 低于阈值直接
`Error: target voltage may be too low for reliable debugging`（实测 1.03 V 时读到全 0）。
**同样的板子 ST CLI 往往还能连**——它不做这个检查。

```bash
# ST 的 bundle 路径带版本号，用 env_doctor 的 [OPT] 行拿到实际路径
"<STM32_Programmer_CLI.exe>" -c port=SWD freq=1000     -w build/<P>/xxx.elf -v -rst
```

成功标志：`File download complete` → `Download verified successfully` → `MCU Reset`

> 结论顺序：**常规用 OpenOCD**；遇到电压/驱动问题时按
> `OpenOCD → ST CLI → 串口 ISP(BOOT0)` 依次降级，**不要急着怀疑芯片坏了**。

### 串口 ISP 兜底（ST-LINK 彻底失效时）

多数 STM32 的 `USART1` 引到排针（如 F407：`PB6=TX / PB7=RX`），
`BOOT0` 拨高 + 复位 → 用 USB-TTL 配合 ST CLI 串口模式烧录。

---

## 2. pyOCD 备选后端

```bash
pyocd flash -t <target> --connect under-reset <你的.bin>   # 或 xxx.elf
```

- `<target>` 见 [01-toolchain.md](01-toolchain.md) §1.2；内置没有就先装 pack：
  ```bash
  pyocd pack install stm32g4      # 按系列；或 pyocd pack install stm32g431rb
  ```
- 需要 `--base-address 0x08000000` 时（传 bin）：
  ```bash
  pyocd flash -t <target> --format bin -a 0x08000000 xxx.bin
  ```

### 已知坑：pyOCD + H7 的 DTCM 写故障

作者环境实测：

```
Memory transfer fault (write) @ 0x20000200-0x2000061f [__main__]
flash program page failure (address 0x08000000; result code 0x1)
```

- 出现在 pyOCD 加载 flash 算法阶段（算法数据段放在 DTCM）
- 同一块板改用 **OpenOCD** 是另一套 flash driver，可作为绕行方案
- 触发条件与 USB 稳定性相关（探针处于"设备描述符请求失败"时必现）
- **对应退出码 2（硬件/环境），不要去改业务代码**

---

## 3. 烧录后一致性校验（不要只看 "programmed N bytes"）

```bash
# 读 PC / SP，与 ELF 复位向量比对
openocd -s "<scripts>" -f interface/stlink.cfg -f target/<系列>.cfg \
        -c "init; halt; reg pc; reg sp; shutdown"

arm-none-eabi-objdump -s -j .isr_vector build/<P>/xxx.elf | head    # 前两字 = 初始 SP / Reset_Handler
```

判据：

- `pc` 落在 `0x0800_0000`（或你的 flash 起址）附近
- `sp` 等于 ELF 向量表第 1 个字
- 注意 **Thumb 末位**：向量表里的地址末位是 1，实际 PC 是偶数地址，比对时忽略末位

---

## 4. 烧录失败分类（对应 exit 2）

| 现象 | 根因 | 下一步 |
|---|---|---|
| `Error: open failed` / `No cores were discovered` | 探针未枚举 / USB 掉线 / 驱动不是 WinUSB | 先 `pyocd list`；拔插换口；查驱动 |
| `Error: init mode failed (unable to connect to the target)` | 目标没电 / SWD 线序错 / 复位被拉死 | 查供电、SWDIO-SWCLK-GND、复位脚 |
| `Error: timed out while waiting for target halted` | Flash 被读保护 / 低功耗模式 | 解除 RDP；用 under-reset 连接 |
| `Memory transfer fault (write) @ 0x2000xxxx` | pyOCD flash 算法写 DTCM 失败 | 换 OpenOCD 后端 |
| `flash program page failure` | flash 未擦除 / 写保护 / 供电不足 | `-e chip` 重试；查 WRP、供电 |
| 烧完行为没变 | 烧了旧产物 / 编译被跳过 | 查产物 sha256 与 mtime（见 03） |

> **重要**：烧录失败后**不要**继续进入串口阶段——那时串口读到的是旧固件，会误导后续判断。
> `flash_loop.py` 在 exit 2 时直接中止。

---

## 5. 量产/多台提示

- 批量烧录可用 `-c "program … verify reset exit"` 串行循环，注意**每次都要 verify**
- 改了 option bytes（RDP/WRP）后**必须先断电重启**再连，否则连接不稳定
- 同一台电脑上 OpenOCD / pyOCD / Keil 调试会话**不能同时占用一个探针**（串行使用）
