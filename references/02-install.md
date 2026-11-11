# 02 · 安装指引（含国内镜像实测结论）

> 原则：**先跑 `env_doctor.py --install-hints`**，只装缺的那几样。
> 下面每条都标注了**实测状态**：✅已验证 / ⚠️部分 / ❓未验证。
> 未验证的只作为候选，实际以 `env_doctor.py --probe-net` 的现场结果为准。

---

## 0. 一句话路径选择

| 要装的东西 | 首选方式 | 备选 |
|---|---|---|
| cmake / ninja / pyocd / pyserial | ✅ **pip + 清华源** | pip + 阿里源 |
| openocd | ✅ **winget（xpack）** | xpack releases 直连 |
| arm-none-eabi-gcc | ARM 官方安装包 | winget xpack / MSYS2 |
| python | 官方安装包 | winget |

---

## 1. Python 包（✅ 实测可用）

```bash
# 清华源（本机实测 200）
python -m pip install -U cmake ninja pyocd pyserial \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

# 阿里源（本机实测 200）
python -m pip install -U cmake ninja pyocd pyserial \
    -i https://mirrors.aliyun.com/pypi/simple/

# 设成默认源（可选）
python -m pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

装完核对：

```bash
cmake --version && ninja --version && python -m pyocd --version
python -c "import serial; print('pyserial', serial.__version__)"
```

---

## 2. OpenOCD（✅ 实测成功：0.12.0-7）

```bash
winget install -e --id xpack-dev-tools.openocd-xpack
```

- 装完 **当前 shell 的 PATH 不生效**，`env_doctor.py` 靠 glob 找得到，不用重开也能用；
  想用命令行 `openocd` 的话重开一个终端。
- 包路径形如：
  `%LOCALAPPDATA%\Microsoft\WinGet\Packages\xpack-dev-tools.openocd-xpack_*\xpack-openocd-0.12.0-7\`
  （**带哈希后缀，不要写死**）
- scripts 目录：`…\xpack-openocd-0.12.0-7\openocd\scripts`（含 `interface/`、`target/`）

**直连备选**：<https://github.com/xpack-dev-tools/openocd-xpack/releases>

### ❌ 关于"清华 github-release 镜像"

实测结论（2026-11）：

```
https://mirrors.tuna.tsinghua.edu.cn/github-release/          → 200（目录存在）
https://mirrors.tuna.tsinghua.edu.cn/github-release/xpack-dev-tools/  → 404
目录清单里没有 xpack-dev-tools（只有 FreeCAD/Homebrew/PowerShell/VSCodium/git-for-windows 等）
USTC 同样：https://mirrors.ustc.edu.cn/github-release/xpack-dev-tools/ → 404
```

→ **不要**告诉用户"从清华镜像下 openocd/gcc"，那条路不存在。要么 winget，要么直连 GitHub。

### 社区加速站（❓ 未验证）

`bgithub.xyz` / `ghproxy.net` / `kkgithub.com` 在作者机器上全部不可达（ERR），
所以只把它们列为候选，由 `env_doctor.py --probe-net` 现场判定，**不要默认推荐**。

---

## 3. ARM GNU Toolchain（arm-none-eabi-gcc / gdb）

### 3.1 官方安装包（推荐，❓ 下载速度视网络）

<https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads>

选 `arm-gnu-toolchain-<ver>-mingw-w64-x86_64-arm-none-eabi.exe`（Windows），
安装时勾 **"Add path to environment variable"**。装完：

```bash
arm-none-eabi-gcc -dumpversion      # 期望 >= 10.3
arm-none-eabi-gdb --version
```

### 3.2 winget（xpack，❓ 包是否存在需现场 `winget search arm-gnu`）

```bash
winget search "arm-none-eabi"
winget install -e --id xpack-dev-tools.arm-none-eabi-gcc
```

> 不同 winget 源里包名可能不同，**先 search 再装**，不要照抄 id。

### 3.3 MSYS2（⚠️ 部分验证）

```bash
# 镜像根可用（TUNA: https://mirrors.tuna.tsinghua.edu.cn/msys2/ 实测 200）
# 但 /msys2/mingw/x86_64/ 在 TUNA 上返回 404（目录布局不同），具体包名与路径需现场确认
pacman -Ss arm-none-eabi        # 先搜
```

### 3.4 Linux / macOS

```bash
# Debian/Ubuntu
sudo apt install gcc-arm-none-eabi gdb-multiarch
# macOS
brew install --cask gcc-arm-embedded
```

---

## 4. Python 本体 & 其他

| 工具 | 安装 | 状态 |
|---|---|---|
| Python 3.8+ | <https://www.python.org/downloads/> 或 `winget install -e --id Python.Python.3.12` | ✅ 常见 |
| git | <https://git-scm.com/downloads>（国内镜像：TUNA/USTC 都有 `git-for-windows`） | ✅ |
| ST-Link 驱动 | ST 官网 STSW-LINK009 | 见 07-troubleshooting #2 |
| 串口驱动（CH340 等） | 厂商驱动 | — |

---

## 5. 装完必做的三件事

```bash
# ① 体检全绿
python scripts/env_doctor.py

# ② 若走 pyOCD 且型号不在内置 18 个里，装 pack
pyocd pack install stm32g4            # 按系列
pyocd list --targets | grep -i stm32  # 核对

# ③ 若下载慢，先测源再决定
python scripts/env_doctor.py --probe-net
```

---

## 6. 安装失败的排查顺序

```
1. 命令存在吗        env_doctor 里是 MISS 还是 BAD（BAD=版本过低）
2. PATH 生效了吗     新开终端再试；Windows 装完常要重登
3. 权限              pip 用 --user；winget 用普通用户即可
4. 网络              换源（pip）/ 换 winget 源 / 直连 GitHub
5. 杀毒/代理拦截     临时关闭或加白名单
6. 仍然不行          把 env_doctor --json 的完整输出贴出来（含 reason 字段）
```
