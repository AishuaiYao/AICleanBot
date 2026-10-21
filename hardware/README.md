# 硬件资料

本目录是 AICleanBot 的完整硬件设计资料，包含选型、电路、结构件与装配说明。

- [物料清单](#物料清单)
- [原理图与手册](#原理图与手册)
- [结构件与 3D 打印](#结构件与-3d-打印)
- [装配流程](#装配流程)
- [线序与检查](#线序与检查)
- [实物参考](#实物参考)

---

## 物料清单

机读版见 [`bom.csv`](bom.csv)。

| # | 类别 | 型号 / 规格 | 数量 | 备注 |
|---|------|------------|:---:|------|
| 1 | 主控 | ESP32-S3-WROOM-1 **N16R8**（8MB Flash + 8MB PSRAM） | 1 | 必须带 PSRAM；也可用 ESP32-S3-CAM 开发板，见 `datasheets/` |
| 2 | 摄像头 | OV2640（24P FPC 或裸板） | 1 | 直连 8 位并口，**不需要**带 FIFO 的 ESP32-CAM 模块 |
| 3 | 电机驱动 | TB6612FNG 模块 | 1 | 双路，本项目只用 1 路 PWM × 2 通道 + 3 号电机 |
| 4 | 驱动电机 | JGA25-370，带 AB 相霍尔编码器 | 2 | 减速比按负载选，建议 1:30 ~ 1:48 |
| 5 | 清洁电机 | 130 / 260 小型直流电机 | 1 | 驱动毛刷/吸水辊，即固件中的「3 号电机」 |
| 6 | 电池 | 3S 18650 或 3S 锂电包，11.1~12.6V | 1 | 容量 ≥ 2000mAh |
| 7 | 降压 | DC-DC 12V→5V，≥ 2A | 1 | 供主控与逻辑侧；建议再加一路 3.3V LDO |
| 8 | 分压电阻 | 100kΩ + 10kΩ（1% 精度） | 各 1 | 电池采样，分压比 1:11 |
| 9 | 车体 | 3D 打印件（外壳 / 底盘 / 水箱） | 1 套 | 见 `cad/` |
| 10 | 轮子 | 65~80mm 橡胶轮 | 2 | 直接压装到 JGA25-370 输出轴 |
| 11 | 万向轮 | 1~1.5 寸 | 1 | 后支撑 |
| 12 | 紧固件 | M3 螺丝/螺母/铜柱套装 | 若干 | — |
| 13 | 电源开关 | 自锁船型开关 10A | 1 | 串在电池正极 |

> **为什么强调 PSRAM**：`sdkconfig.defaults.esp32s3` 打开了 `CONFIG_SPIRAM=y`，摄像头帧缓冲指定 `CAMERA_FB_IN_PSRAM`。没有 PSRAM 的模组能编译通过，但运行到 `esp_camera_init` 必然崩。

---

## 原理图与手册

| 文件 | 内容 |
|------|------|
| [`datasheets/esp32-s3-cam-schematic.pdf`](datasheets/esp32-s3-cam-schematic.pdf) | ESP32-S3-CAM 开发板原理图（摄像头接口、USB、电源） |
| [`datasheets/tb6612-motor-driver-manual.pdf`](datasheets/tb6612-motor-driver-manual.pdf) | 塔克创新 TB6612 四路编码器电机驱动用户手册（引脚定义、使能逻辑、编码器接线） |
| [`pcb/linepatrol-carrier.eprj2`](pcb/linepatrol-carrier.eprj2) | 嘉立创 EDA 工程（载板）。用 [嘉立创 EDA 专业版](https://pro.lceda.cn/) 打开 |

### 主控与摄像头的连接

摄像头通过 8 位并口直连 ESP32-S3，引脚定义见主 README 的[引脚接线](../README.md#引脚接线)表。注意**数据线顺序**是唯一一个接错后不会有任何报错提示的点——表现是画面全黑或花屏，日志却一切正常。

板载接口参考：[`photos/board-pinout.jpg`](photos/board-pinout.jpg)、尺寸：[`photos/board-dimensions.jpg`](photos/board-dimensions.jpg)。

### 电机驱动侧

TB6612FNG 关键点：

- `STBY` 必须拉高（悬空 = 电机完全不动，且日志显示 `START` 成功）
- `VM` 接电池正极（电机电源），`VCC` 接 3.3V（逻辑电源），两者**不要共用一个电源**
- 每个电机需要 3 根线：`PWMA/PWMB` + 两个方向脚
- 本项目为了省 GPIO，把**左右轮的 IN1 并联到 GPIO2、IN2 并联到 GPIO42**，只保留独立 PWM。代价是无法原地自转，只能差速转向

如果你手上的板子 GPIO 富余，把左右方向脚拆开后改 `main/app_main.cpp` 顶部：

```cpp
#define MOTOR_L_IN1   GPIO_NUM_2
#define MOTOR_L_IN2   GPIO_NUM_42
#define MOTOR_R_IN1   GPIO_NUM_xx    // 改成独立引脚
#define MOTOR_R_IN2   GPIO_NUM_yy
```

### 电池采样

```
BAT+ ──[100kΩ]──┬──[10kΩ]── GND
                │
             GPIO1 (ADC1_CH0)
```

分压比 1:11，对应固件 `#define BAT_VOLTAGE_DIVIDER 11`。

> 直接用 12V 接 ADC 引脚会立刻烧毁芯片。

---

## 结构件与 3D 打印

### 模型文件

| 文件 | 说明 | 体积 |
|------|------|------|
| [`cad/shell.stl`](cad/shell.stl) | 外壳（含清洁机构安装位） | 10.5 MB |
| [`cad/chassis.stl`](cad/chassis.stl) | 底盘（电机、万向轮、电池仓） | 1.0 MB |
| [`cad/water-tank.stl`](cad/water-tank.stl) | 水箱 | 0.4 MB |

单位：**毫米**。可直接切片，无需缩放。

### 建议打印参数

以下为实测可用的一组参数，不是唯一解，按你的打印机调整：

| 项 | 建议值 |
|----|--------|
| 材料 | PLA（外壳）/ PETG（水箱，需一定韧性） |
| 层高 | 0.2 mm |
| 壁厚 | 3 圈（约 1.2 mm） |
| 填充 | 20%~30%（外壳）/ 15%（水箱） |
| 支撑 | 底盘需要；外壳视摆放方向而定 |
| 底盘/外壳拼接 | M3 螺丝 + 热熔铜螺母，或直接胶接 |

水箱务必做**水密性测试**再上车——PLA 长期接触水会缓慢降解，建议 PETG 或内壁刷防水涂层。

### 装配顺序

按这个顺序装，返工最少：

1. **底盘**：压入 JGA25-370，固定万向轮，装电池仓
2. **电气先通电测试**：主控 + 摄像头 + 驱动板先裸接，用 `idf.py flash monitor` 确认摄像头出图、电机能转、编码器有计数
3. **上车**：把测试通过的电气件固定到底盘
4. **外壳**：装清洁电机与毛刷，扣上外壳
5. **水箱**：水密测试通过后再装
6. **走线**：摄像头排线远离电机线，避免 PWM 干扰导致画面横纹

> 第 2 步不要跳过。装完再发现问题，拆一次的成本远高于先测。

---

## 线序与检查

- [ ] 摄像头 D0-D7 顺序（最容易错，且无报错）
- [ ] TB6612 `STBY` 拉高
- [ ] 电机电源 `VM` 独立于逻辑电源 `VCC`
- [ ] 编码器 A/B 两相都接（只接 A 相能走直线但速度环失效）
- [ ] 电池分压电阻阻值正确（100k / 10k）
- [ ] 左右电机接到对应通道（接反表现为「让它左转它右转」）
- [ ] 所有 GND 共地

---

## 实物参考

### 组装完成

| | | |
|---|---|---|
| ![1](photos/robot-photo-1.jpg) | ![2](photos/robot-photo-2.jpg) | ![3](photos/robot-photo-3.jpg) |

### 结构与装配过程

| | | |
|---|---|---|
| ![4](photos/robot-photo-4.jpg) | ![5](photos/robot-photo-5.jpg) | ![6](photos/robot-photo-6.jpg) |

### 3D 打印件

| | | |
|---|---|---|
| ![p1](photos/print-1.jpg) | ![p2](photos/print-2.jpg) | ![p3](photos/print-3.jpg) |
| ![p4](photos/print-4.jpg) | ![p5](photos/print-5.jpg) | ![p6](photos/print-6.jpg) |

### 电路与走线

| | |
|---|---|
| ![w1](photos/board-wiring-1.jpg) | ![w2](photos/board-wiring-2.jpg) |

### 概念设计

| | | |
|---|---|---|
| ![c1](photos/concept-1.jpg) | ![c2](photos/concept-2.jpg) | ![c3](photos/concept-3.jpg) |
| ![c4](photos/concept-4.jpg) | ![c5](photos/concept-5.jpg) | ![c6](photos/concept-6.jpg) |

### 三视图与轴测

| | | |
|---|---|---|
| ![f](photos/render-front.jpg) | ![s](photos/render-right.jpg) | ![t](photos/render-top.jpg) |
| ![p1](photos/render-perspective-1.jpg) | ![p2](photos/render-perspective-2.jpg) | ![b](photos/render-bottom.jpg) |
