# 03 · 编译（CMake + Ninja + arm-none-eabi-gcc）

> 适用**全系列 STM32**：本 skill 不关心你用的是哪颗，只要求能产出 `.elf` / `.bin`。
> 系列差异（`-mcpu` / FPU / 链接脚本）在**工程的** `cmake/gcc-arm-none-eabi.cmake` 里，不在这里。

---

## 1. 预设（CMakePresets.json）

```bash
cmake --list-presets                 # 看有哪些 configure preset
cmake --preset Release               # 首次生成 build/Release
cmake --build --preset Release       # 日常增量编译
```

推荐三档（工程里没有就加，别改现有 `Release` 的优化参数）：

| 预设 | 典型参数 | 用途 |
|---|---|---|
| `Debug` | `-Og -g3 -gdwarf-4` | 源码级调试（断点/单步） |
| `RelWithDebInfo` | `-Os -g3 -gdwarf-4` | 体积优化 + 可调试（**推荐做默认调试档**） |
| `Release` | `-Os -g0` | 出厂；**没有调试信息** |

> 判断"有没有调试信息"：
> ```bash
> arm-none-eabi-objdump --dwarf=info build/<P>/*.elf | head
> ```
> `.debug_info` 段很小（几百字节）就说明是 `-g0`，源码级调试会失败。

### 加一个 RelWithDebInfo 预设（示例，改前先备份 CMakePresets.json）

```json
{ "name": "RelWithDebInfo", "inherits": "Release", "cacheVariables": {
    "CMAKE_BUILD_TYPE": "RelWithDebInfo" } }
```
并在 `cmake/gcc-arm-none-eabi.cmake` 里补：
```cmake
set(CMAKE_C_FLAGS_RELWITHDEBINFO "-Os -g3 -gdwarf-4")
```

---

## 2. 产物定位

默认：`build/<Preset>/<工程名>.elf` / `.bin`。

```bash
arm-none-eabi-size -A build/Release/*.elf      # 段大小
arm-none-eabi-objdump -h build/Release/*.elf   # 段表
ls build/Release/*.bin
```

`config/project.json` 里显式写死路径最稳（auto 通配只适合单产物工程）：

```json
"build": { "preset": "Release", "elf": "build/Release/xxx.elf", "bin": "build/Release/xxx.bin" }
```

---

## 3. 错误解析（exit 1）

GCC 输出天然带 `文件:行:列`，直接抓：

```bash
cmake --build --preset Release 2>&1 | grep -E "error:|undefined reference|No such file"
```

常见三类：

| 输出 | 含义 | 处理 |
|---|---|---|
| `fatal error: xxx.h: No such file or directory` | 头文件路径没进 `target_include_directories` | 加 include 路径，**不要**拷贝头文件 |
| `undefined reference to 'xxx'` | 源文件没进 `target_sources` / 库没链接 | 查 CMakeLists 与链接顺序（被依赖者放后面） |
| `region 'RAM' overflowed by N bytes` | 链接脚本区域放不下 | 查 `.bss/.data` 大小；STM32 上常见于把大数组放进 DTCM |

### 系列相关的两个高频坑

| 坑 | 说明 |
|---|---|
| **DMA 访问不到 DTCM** | DTCM（`0x2000_0000`）只有 CPU/MDMA 能访问，DMA1/DMA2 读写会失败。放大缓冲（LCD 显存、DMA 收发环）要放 **AXI SRAM（`0x2400_0000`，H7）或普通 SRAM** |
| **H7 的 RAM 分区多** | `DTCM / AXI(D1) / SRAM1-3(D2) / SRAM4(D3)`，链接脚本要按用途分配，别默认全塞 `.bss` |

---

## 4. 产物新鲜度（闭环第 ② 步）

`flash_loop.py` 会在编译前后各取一次 `sha256`：

- 变了 → 继续烧
- 没变 → **exit 5**（"没有新产物，禁止烧"），因为烧旧固件会得出完全错误的结论

手工等价检查：

```bash
sha256sum build/Release/*.bin     # Linux/macOS
certutil -hashfile build\Release\xxx.bin SHA256   # Windows
```

> 已知坑：用脚本恢复源码时若保留旧 mtime（`copy2`），CMake 会认为 up-to-date 跳过重编译，
> 于是"改了代码但产物没变"。修复：`touch` 源文件，或断言构建输出里出现链接行。

---

## 5. 编译完成的最低验收

```
① 退出码 0
② .elf 与 .bin 都存在且时间戳更新
③ arm-none-eabi-size 看 FLASH/RAM 占用没有超
④ 若要做调试：确认 .debug_info 存在
```

之后进入 [04-flash.md](04-flash.md)。
