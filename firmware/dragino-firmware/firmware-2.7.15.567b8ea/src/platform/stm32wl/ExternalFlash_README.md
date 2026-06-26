# External SPI Flash 文件系统说明

## 概述

本实现为 STM32WL 平台添加外部 SPI Flash 文件系统支持，使用 LittleFS 作为文件系统层，
可替代内部 Flash 用于 Meshtastic 配置存储。通过编译宏 `USE_EXTERNAL_FLASH` 在内部/外部
Flash 之间切换，不影响其他代码。

## 文件结构

```
src/platform/stm32wl/
├── ExternalFlashFS.h          # ExternalFlashFS 类声明，extern ExternalFS 全局实例
├── ExternalFlashFS.cpp        # SPI Flash 驱动 + LittleFS 后端实现
├── LittleFS.h / LittleFS.cpp  # 内部 Flash FS（InternalFS，不受影响）
├── STM32_LittleFS.h/.cpp      # 两者共用的 LittleFS 基类
└── reference/
    ├── zb25vq32.h             # ZB25VQ32 芯片头文件（仅参考，不编译）
    └── zb25vq32.c             # ZB25VQ32 HAL 驱动（仅参考，不编译）
```

`src/FSCommon.h` 通过条件编译决定使用哪个文件系统：

```cpp
#if defined(ARCH_STM32WL)
  #if defined(USE_EXTERNAL_FLASH)
    #include "ExternalFlashFS.h"
    #define FSCom ExternalFS        // 使用外部 Flash
  #else
    #include "LittleFS.h"
    #define FSCom InternalFS        // 使用内部 Flash（默认）
  #endif
#endif
```

---

## 硬件规格（ZB25VQ32）

本实现针对 **Zbit ZB25VQ32** SPI NOR Flash，参数如下：

| 参数 | 值 |
|------|----|
| 容量 | 32Mbit = **4MB** |
| JEDEC ID | `0x5E4016`（制造商 `0x5E`，类型 `0x40`，密度 `0x16`） |
| 页大小 | 256 字节 |
| 扇区大小 | 4KB（LittleFS 擦除块单位） |
| 块大小 | 64KB |
| 页编程时间 | 典型 500µs，最大 **3ms** |
| 扇区擦除时间 | 典型 45ms，最大 **200ms** |
| SPI 模式 | Mode 0（CPOL=0, CPHA=0），MSB 先行 |
| 最大 SPI 频率 | 104MHz（代码使用 4MHz，安全保守） |

### 硬件连接

| Flash 引脚 | STM32WL 引脚 | 说明 |
|-----------|-------------|------|
| SCK | **PA5** | SPI1_SCK（AF5） |
| MISO | **PA6** | SPI1_MISO（AF5） |
| MOSI | **PA7** | SPI1_MOSI（AF5，PULLDOWN） |
| CS | **PA4** | GPIO 输出，空闲高电平 |
| VCC | 3.3V | |
| GND | GND | |

> **关于 SPI 总线冲突**：STM32WL 的 LoRa 射频（SX126x）使用芯片内部的 **SUBGHZSPI**，
> 与外部 SPI1 完全独立，不存在总线冲突，无需任何互斥锁处理。

---

## 启用外部 Flash

### 方法一：在 `platformio.ini` 中添加编译标志（推荐）

```ini
[env:wio-e5]
build_flags =
    ${common.build_flags}
    -DUSE_EXTERNAL_FLASH
```

### 方法二：在 `variant.h` 中定义

```cpp
#define USE_EXTERNAL_FLASH
```

---

## 引脚配置

默认引脚已与参考驱动一致，**无需修改**即可直接使用。
若板卡布线不同，在 `variant.h` 中覆盖以下宏：

```cpp
// 覆盖默认引脚（只在布线不同时才需要）
#define FLASH_CS_PIN   PB0   // 示例：修改 CS 引脚
#define FLASH_SPI_MOSI PA7   // 示例：MOSI（通常不需改）
#define FLASH_SPI_MISO PA6   // 示例：MISO（通常不需改）
#define FLASH_SPI_SCK  PA5   // 示例：SCK（通常不需改）
```

> **注意**：代码内部使用 `SPIClass(MOSI, MISO, SCK)` 构造方式。
> STM32duino 会根据引脚的复用功能（AF）自动选择正确的 SPI 外设（SPI1）。
> 不能直接使用 `SPI1`——在 STM32duino 中它是 HAL 寄存器宏，不是 `SPIClass` 对象。

---

## LittleFS 配置说明

代码中的 `lfs_config` 参数如下，已针对 SPI Flash 特性优化：

| 参数 | 值 | 原因 |
|------|----|------|
| `read_size` | **1** | SPI Flash 支持任意字节数读取，无最小对齐要求 |
| `prog_size` | **256** | 匹配 SPI Flash 页编程粒度（256 字节/页） |
| `block_size` | **4096** | 匹配扇区擦除粒度（4KB） |
| `block_count` | **1024** | 4MB / 4KB = 1024 块 |
| `lookahead` | **128** | 块分配前瞻缓冲（128 bits = 128 块） |

> **与内部 Flash 的区别**：内部 Flash 因 STM32WL 页编程要求，
> `read_size = prog_size = block_size = 2048`，每个操作占用 2KB 缓冲。
> 外部 Flash 使用 `read_size=1, prog_size=256`，LittleFS 内部缓冲仅需约 **512 字节**，
> 节省约 **8KB** RAM，对 STM32WL（64KB RAM）非常重要。

> **LittleFS 版本**：本项目使用 **LittleFS v1.6**（`LFS_VERSION 0x00010006`）。
> `block_cycles` 字段是 v2 特性，**不可**在此使用，否则编译报错。

---

## 编译与烧录

```bash
# 编译 wio-e5 目标（已在 platformio.ini 添加 USE_EXTERNAL_FLASH）
pio run -e wio-e5

# 编译并上传
pio run -e wio-e5 -t upload
```

---

## 验证与调试

### 串口日志（需启用 CFG_DEBUG）

启用调试后，初始化时应看到：

```
SPI Flash JEDEC ID: 0x5E4016
Detected ZB25VQ32 (4MB SPI Flash)
```

若看到以下输出，文件系统已正常挂载：

```
Filesystem files:
```

### 启用调试输出

在 `platformio.ini` 中添加：

```ini
build_flags =
    -DUSE_EXTERNAL_FLASH
    -DCFG_DEBUG=1
```

---

## 故障排查

### Flash 未响应（JEDEC ID = 0x000000 或 0xFFFFFF）

| 可能原因 | 排查方法 |
|---------|---------|
| 引脚接线错误 | 对照硬件连接表检查 SCK/MOSI/MISO/CS |
| CS 引脚定义不对 | 确认 `FLASH_CS_PIN` 与实际电路一致 |
| SPI 引脚未启用 AF5 | STM32duino `SPI1.begin()` 会自动配置，检查引脚是否被其他外设占用 |
| Flash 芯片未上电 | 检查 VCC 和 GND 连接 |
| SPI 时钟过快 | 可临时将 `EXT_FLASH_SPI_FREQUENCY` 改为 `1000000`（1MHz）排查 |

### 文件系统挂载失败

- 首次使用会自动格式化后重新挂载，属正常现象
- 若反复格式化失败，检查 `EXT_FLASH_TOTAL_SIZE` 是否与芯片实际容量一致
- 确认 `block_size = 4096`（须等于扇区大小）

### 编译错误：`lvalue required as unary '&' operand`

原因：尝试使用 `&SPI1`（HAL 宏，非左值）。
正确做法：使用 `SPIClass(MOSI, MISO, SCK)` 构造实例，代码已正确处理，
若仍出现此错误，检查是否有其他地方引用了 `SPI1`。

---

## 切换回内部 Flash

移除 `USE_EXTERNAL_FLASH` 宏定义后重新编译即可，其余代码无需任何改动。

```ini
# platformio.ini - 注释掉或删除该行
# -DUSE_EXTERNAL_FLASH
```
