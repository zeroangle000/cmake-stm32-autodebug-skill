# 05 · 调试（GDB + OpenOCD / pyOCD，全系列 STM32）

> 调试的前提是**产物带调试信息**。Release 常是 `-Os -g0`，必须先换 `Debug` / `RelWithDebInfo`。
> 系列差异只在 `target/*.cfg` 与 pyOCD `-t` 名，流程一致。

---

## 1. DWARF 门禁（先做，纯离线，不占探针）

```bash
arm-none-eabi-objdump --dwarf=info build/<P>/xxx.elf | head -20
```

| 结果 | 结论 |
|---|---|
| 有大量 `DW_TAG_compile_unit` / `DW_AT_name` | ✅ 可做源码级调试 |
| 段几乎为空 / 报 `no recognized debugging information` | ❌ `-g0`；换预设重编 |

快速判断段大小：

```bash
arm-none-eabi-objdump -h build/<P>/xxx.elf | grep -E "debug_info|debug_line"
```
`.debug_info` 只有几百字节 → 就是没有（正常应有几十 KB 以上）。

---

## 2. 起调试会话

### 方案 A：OpenOCD + arm-none-eabi-gdb（推荐，全系列）

```bash
# 终端 1：起服务器（halt 住内核，等 gdb 连）
openocd -s "<scripts>" -f interface/stlink.cfg -f target/<系列>.cfg \
        -c "gdb_port 3333; telnet_port 4444"

# 终端 2：连
arm-none-eabi-gdb build/<P>/xxx.elf \
  -ex "target extended-remote :3333" \
  -ex "monitor reset halt" \
  -ex "load" \
  -ex "break main" \
  -ex "continue"
```

常用：

```
bt                  # 调用栈（HardFault 里看谁崩的）
info registers      # 寄存器
x/16wx 0x24000000   # 看内存
monitor reset halt  # 复位后停住（★ 会毁掉当前现场）
```

### 方案 B：pyOCD gdbserver

```bash
pyocd gdbserver -t <target> --port 3333          # 终端 1
arm-none-eabi-gdb build/<P>/xxx.elf -ex "target extended-remote :3333" -ex "monitor reset halt"
```

> pyOCD 内置 target 不足时先 `pyocd pack install <part>`（见 01-toolchain.md §1.2）。

---

## 3. 三条容易踩的语义

| 现象 | 原因 | 正确做法 |
|---|---|---|
| `monitor reset` 后 `info registers` 还是旧值 | reset 由 OpenOCD 侧执行，gdb 收不到 `*stopped`，寄存器/栈帧缓存未刷新 | 认可 `monitor reset halt` 的**回显 pc/sp**；或在目标函数上下断点、命中后再读 |
| 断点"设成功但不生效" | Cortex-M 硬件断点数量有限（M3/M4/M7：6 个 FPB；M0/M0+：4 个） | 用完 `delete`；必要时改用临时断点 |
| 复位后程序不跑 | 调试器停在内核 halt | `monitor reset run` / `continue`，或断开调试器后重新上电 |

**reset 会毁掉现场**：排查死机/卡死时**先 attach 读现场**，再考虑 reset。

---

## 4. 崩溃定位（HardFault / BusFault / UsageFault）

```
1. 停下后先读 SCB 寄存器
   gdb> p/x *(unsigned long*)0xE000ED28    # CFSR
   gdb> p/x *(unsigned long*)0xE000ED34    # MMFAR（MemManage 地址）
   gdb> p/x *(unsigned long*)0xE000ED38    # BFAR（BusFault 地址）
2. bt                                     # 调用栈
3. 用 PC/LR 反查源码行
   arm-none-eabi-addr2line -e build/<P>/xxx.elf -f -C 0x0800xxxx
```

| 寄存器值特征 | 常见根因 |
|---|---|
| `CFSR` 的 `IMPRECISERR`(bit10) | 写坏了指向 RAM 的指针（越界/野指针），需看 BFAR |
| `CFSR` 的 `PRECISERR`(bit9) | 访问了不存在的外设/未使能时钟的寄存器 |
| `CFSR` 的 `UNDEFINSTR` | 跑飞（函数指针为空、栈被踩） |
| `HFSR.FORCED` | 由上面某位触发，先看 CFSR |

> 有的工程会在 HardFault 里打印寄存器块到串口（"UART 崩溃自述"），
> 这时可以直接从串口日志解析，不必接调试器。

---

## 5. 系列相关注意

| 系列 | 注意 |
|---|---|
| **C0/F0/L0/G0（Cortex-M0/M0+）** | 断点只有 4 个；没有 FPU；`-mcpu=cortex-m0plus` |
| **F1/F2/L1（M3）** | 6 个断点；无 FPU |
| **F3/F4/L4/G4（M4）** | 有 FPU，注意 `-mfpu=fpv4-sp-d16` 与 lazy stacking |
| **F7/H7（M7）** | 有 D-Cache：DMA 缓冲要看 cache 一致性（`SCB_CleanDCache_by_Addr` / MPU non-cacheable） |
| **L5/U5/H5（M33）** | TrustZone：非安全区调试需 `-c "targets"` 选对核；`TZEN` 影响能否访问安全区 |
| **WB/WBA（双核）** | CPU2 在跑时无法完整调试 CPU1 的 flash 操作，先停 CPU2 |

---

## 6. 收尾（避免留下占着探针的进程）

```
gdb> monitor reset halt      # 让目标停在复位态（避免带病继续跑）
gdb> quit
# 终端 1 Ctrl+C 结束 openocd；或
taskkill /F /IM openocd.exe
```

> 收尾后板子通常保持 halt（不跑），**再复位/上电一次**即可恢复正常运行，这不是故障。
> `env_doctor.py` 会检查残留 `openocd/pyocd` 进程；`--fix --yes` 可清理。
