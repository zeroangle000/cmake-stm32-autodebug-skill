# 07 · 实测踩坑清单（12 条）

> 每条都标注了**是否已在真机上复现**，⏳ 表示"逻辑上成立，但作者环境暂未完成复现"。
> 排查顺序建议：物理层 → 时钟/电源 → 驱动/寄存器 → 应用 → 协议。

---

## 1. pyOCD 烧 H7：`Memory transfer fault (write) @ 0x2000xxxx`

```
Memory transfer fault (write) @ 0x20000200-0x2000061f [__main__]
flash program page failure (address 0x08000000; result code 0x1)
```

- **已复现**。发生在 pyOCD 加载 flash 算法（算法数据段落在 DTCM）阶段
- 伴随现象：探针在系统里显示「未知 USB 设备(设备描述符请求失败)」
- 对策：① 换 **OpenOCD** 后端（不同 flash driver）；② 拔插 ST-Link / 换 USB 口 / 板子断电重上电；③ 结束时 `env_doctor --fix --yes` 清残留进程
- **归类：exit 2（环境/硬件），不要去改业务代码**

## 2. OpenOCD：`Error: open failed`

- **已复现**（探针未枚举时）
- 排查次序：
  ```
  1) pyocd list            → 探针是否被枚举（pyocd 用自己的 libusb）
  2) Get-PnpDevice         → 是否出现「未知 USB 设备(设备描述符请求失败)」
  3) 换 USB 口 / 换线 / 板子供电
  4) 驱动：ST-Link 官方驱动正常；若换过 Zadig/WinUSB 后 openocd 能连、pyocd 不能（或反之），
     就是驱动栈不匹配 —— 二者对 ST-Link 的驱动要求不同，**别同时折腾**
  ```

## 3. Windows 上「未知 USB 设备(设备描述符请求失败)」

- **已复现**
- 含义：USB 枚举阶段就失败，和固件无关
- 对策：拔插、换口（避开 hub）、板子独立供电、检查线材

## 4. `could not open port COMx: PermissionError`

- **已复现**
- 根因：上位机 / 串口助手 / 另一个 python 进程占着
- 对策：关掉占用者；`env_doctor.py` 的 `serial.busy` 会直接标红；Windows 可用
  `Get-CimInstance Win32_SerialPort` 或 Process Explorer 查句柄

## 5. CH340 假死（电机一转就掉线）

- **已复现**（台架驱动电机时反复出现）
- 表现：之前能通，电机启动瞬间 `WriteFile failed / PermissionError`，之后端口从系统消失
- 对策：拔插 / 换口；缩短 USB 线、加磁环；串口脚本必须**自动重连**；
  测试脚本崩溃后要 `finally` 停掉电机并关闭调试流

## 6. 烧完行为没变（烧了旧产物）

- **已复现**
- 根因：① 产物是旧的（编译被跳过）；② 烧到了另一份 `.bin`
- 对策：`flash_loop.py` 的 sha256 新鲜度检查；确认 `config.build.bin` 指向正确产物
- 相关坑：用脚本恢复源码时 `shutil.copy2` 保留旧 mtime → CMake 认为 up-to-date 跳过重编译。
  修复：`copyfile` + `os.utime`，并断言构建输出里出现链接行（`FLASH:`/`Memory region`）

## 7. `build/` 里没有新 bin

- **已复现**
- 对策：`touch` 任一源文件后重编；或删 `build/<Preset>` 重新 `cmake --preset`

## 8. 字节守恒断言不成立（`@RX` 的 total≠acc≠cons）

- **已复现**（UART DMA 环缓 + 非阻塞 TX 的实现里）
- 根因举例：TX 环缓 tail 用"重算 used"推进 → 跳过尚未发送的数据
- 对策：按"本次提交长度"推进 tail；用 `total==acc==cons && ovf==0 && late==0 && pend==0` 做回归

## 9. 目标被 LCD/调试页面每轮覆盖

- **已复现**（台架上"串口发的命令不生效，屏幕一动就跑偏"）
- 根因：页面任务周期性重设目标，抢占同一批全局变量
- 对策：测试前先退出页面（如 `PAGE 0`）、关掉串口绘图流（`DJIPLOT 0`）

## 10. CAN 侧 0V / 扫不到电机

- **已复现**（板级电源使能脚未配）
- 根因：板子的 `OUT1_EN`/`5V_EN` 没置高 → 电机 24V 与 CAN 收发器 5V 都没有
- 对策：先量 `CAN_H/CAN_L` 空闲应为 ~2.5V（不是 0V）；查板级电源使能脚

## 11. "掉线过半"误判导致断电

- **已复现**
- 根因：分母把"从未上线过"的设备也算进去（例如只接了 1 台，另一路是空的）
- 对策：分母只统计"曾经在线过"的；单台掉线只让该路归零，不做全局断电

## 12. Release 下断点无效 / 无源码级调试

- **已复现**
- 根因：`-Os -g0`，没有 `.debug_info`
- 对策：用 `Debug` 或新增 `RelWithDebInfo`（`-Os -g3 -gdwarf-4`）；
  调试前跑 [05-debug.md](05-debug.md) §1 的 DWARF 门禁

---

## 13. OpenOCD 报 `Target voltage: 1.0x V` 且所有内存读数为 0

- **已复现**（STM32F407VE + ST-Link V2，2026-11）
- 现象：
  ```
  Info : Target voltage: 1.083027
  Error: target voltage may be too low for reliable debugging
  xPSR: 0x01000000 pc: 0x0800509c msp: 0x20020000     # halt 能成功
  mdw 0x40011000 4  →  SR=0 DR=0 BRR=0 CR1=0          # 读数全 0
  ```
- 含义：ST-Link 的 **VTREF 只测到 ~1.0 V**（正常应接近 3.3 V）。
  此时"halt / 读 PC"可能还能工作，但**内存读写不可信**（全 0 或静默失败），
  所以**不能拿这些读数判断固件行为**。
- 对策：
  1. 确认板子 3.3 V 供电（USB/DC 都接上，量 VDD-GND 应为 3.3 V）
  2. 确认 ST-Link 的 VTREF/3V3 与板子 3.3 V 相连、GND 共地
  3. 换 USB 口/线（供电不足常见）
- 注意：**烧录 + verify 可能仍然成功**（flash 算法在目标上跑），
  所以"烧录成功"不能反证"调试链路正常"——两者要分开验。

---

## 附：⏳ 待验证（作者板子恢复正常后补）

| # | 项目 | 验证方法 |
|---|---|---|
| A | OpenOCD 在本项目能否烧通（绕开 pyOCD 的 DTCM 故障） | `program … verify reset exit` 后读 pc/sp 比对向量表 |
| B | `open failed` 是驱动还是连接 | 同一探针分别用 pyocd / openocd 连，对照 PnP 状态 |
| C | 串口令牌闭环（halt→开串口→go→@PONG） | `flash_loop.py` 全流程 3 次 |
| D | RelWithDebInfo 断点/单步 | gdb 命中 main、单步、读局部变量 |
| E | CH340 假死的稳定复现条件 | 电机阶跃 + 串口连续读，统计掉线次数 |

> 这些条目验证完成后，请把结果补回本文件并把 ⏳ 去掉——**不要把没验证过的写成结论**。
