# LinePatrol V1 - 智能巡线机器人

基于 ESP32-S3 的实时语义分割巡线机器人，结合深度学习与嵌入式系统，支持微信小程序控制和数据采集。

![架构图](py_scripts/figure/architecture.jpg)

---

## 项目概述

本项目实现了一个可采集训练数据、自动标注、模型训练、边缘部署的完整闭环系统：

```
┌─────────────────┐      WiFi       ┌──────────────────┐
│   微信小程序    │◄───────────────►│    ESP32-S3      │
│  (控制/采集)   │   TCP/UDP       │  (推理/执行)      │
└─────────────────┘                 └──────────────────┘
        │                                    │
        │                                    ▼
        │                          ┌──────────────────┐
        │                          │  灰度摄像头      │
        │                          │  电机+编码器     │
        │                          │  电池ADC         │
        │                          └──────────────────┘
        │
        ▼
┌─────────────────┐      USB       ┌──────────────────┐
│   PC端工具      │◄───────────────►│  Python训练脚本  │
│  (标注/训练)    │                 │  (PyTorch/ONNX)  │
└─────────────────┘                 └──────────────────┘
```

---

## 目录结构

```
AICleanBot/
├── main/                      # ESP32-S3 固件
│   ├── app_main.cpp           # 主程序：采集、推理、WiFi、电机控制
│   ├── inference_test.cpp     # 模型推理测试
│   ├── motor_encoder_test.cpp  # 电机编码器测试
│   ├── models/                # 部署模型 (.espdl)
│   ├── CMakeLists.txt
│   └── idf_component.yml     # 组件依赖
│
├── py_scripts/                # Python 工具链
│   ├── net/                   # 神经网络
│   │   ├── train_teacher.py   # 教师模型训练
│   │   ├── train_student.py   # 学生模型训练 (知识蒸馏)
│   │   └── quantize_onnx_model.py  # ONNX量化
│   ├── utils/                 # 工具脚本
│   │   ├── capture_img_serve.py  # ESP32图像服务器
│   │   ├── capture_img_client.py # PC采集客户端
│   │   ├── label_tool.py         # 数据标注工具
│   │   ├── tools.py              # 模型转换工具
│   │   └── inference_test.py     # PC端推理测试
│   ├── dataset/              # 数据集
│   │   ├── FRAME_QQVGA/     # 原始图像 (160x120)
│   │   └── FRAME_QQVGA_label/  # 标签图像
│   └── models/               # 训练模型 (.pth/.onnx/.espdl)
│
├── smartcat/                  # 微信小程序 (见 smartcat/README.md)
│
├── logs/                      # 编译日志
├── build/                     # 编译输出
├── bin/                       # 烧录固件
└── README.md                  # 本文档
```

---

## 硬件架构

### 硬件清单

| 组件 | 型号/说明 |
|------|----------|
| 主控 | ESP32-S3-WROOM-1 |
| 摄像头 | ESP32-CAM (OV2640) |
| 电机驱动 | TB6612FNG |
| 电机 | JGA25-370 编码器电机 |
| 电池 | 12V 锂电池 |

### 引脚定义

#### 摄像头接口

| 功能 | GPIO | 说明 |
|------|------|------|
| XCLK | GPIO15 | 摄像头时钟 20MHz |
| SDA | GPIO4 | SCCB数据 |
| SCL | GPIO5 | SCCB时钟 |
| D0-D7 | GPIO11,9,8,10,12,18,17,16 | 数据总线 |
| VSYNC | GPIO6 | 帧同步 |
| HREF | GPIO7 | 行同步 |
| PCLK | GPIO13 | 像素时钟 |

#### 电机驱动 (TB6612FNG)

| 功能 | GPIO |
|------|------|
| 左轮 PWM | GPIO39 |
| 左轮 IN1 | GPIO45 |
| 左轮 IN2 | GPIO48 |
| 右轮 PWM | GPIO14 |
| 右轮 IN1 | GPIO2 |
| 右轮 IN2 | GPIO42 |

#### 编码器 (JGA25-370)

| 功能 | GPIO |
|------|------|
| 左编码器 A相 | GPIO47 |
| 左编码器 B相 | GPIO21 |
| 右编码器 A相 | GPIO41 |
| 右编码器 B相 | GPIO40 |

#### 其他

| 功能 | GPIO | 说明 |
|------|------|------|
| 电池电压 | GPIO1 | ADC1_CH0, 分压比 1/11 |

---

## 通信协议

### WiFi AP

- SSID: `ESP32-CAM`
- 密码: `12345678`
- IP: `192.168.4.1`

### 网络端口

| 协议 | 端口 | 用途 |
|------|------|------|
| TCP Server | 5000 | 控制命令传输 |
| UDP Server | 5001 | 视频流传输 |

### UDP 数据包格式 (第一分片)

```
[帧号 2B][总分片 1B][索引 1B][电压 1B][左PWM 1B][右PWM 1B][编码器L 2B][编码器R 2B][图像数据...]
```

---

## 工作流程

### 完整训练部署流程

```
┌────────────────────────────────────────────────────────────────────────┐
│                           数据采集阶段                                  │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  1. 启动ESP32热点 (SSID: ESP32-CAM)                                    │
│                                                                        │
│  2. 连接微信小程序，进入"数据采集"页面                                  │
│                                                                        │
│  3. 遥控机器人移动，采集图像数据                                        │
│     - 实时视频流显示                                                   │
│     - 编码器数据记录                                                   │
│     - 可保存为本地图片                                                  │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                           PC端标注阶段                                  │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  4. 传输采集数据到PC                                                    │
│                                                                        │
│  5. 使用教师模型自动标注                                               │
│     python py_scripts/utils/label_tool.py                              │
│                                                                        │
│  6. 人工校正标注结果                                                    │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                           模型训练阶段                                  │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  7. 训练学生模型 (知识蒸馏)                                             │
│     python py_scripts/net/train_student.py                             │
│                                                                        │
│  8. 导出 ONNX 模型                                                     │
│                                                                        │
│  9. 量化模型 (FP32 → INT8)                                             │
│     python py_scripts/net/quantize_onnx_model.py                        │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                           边缘部署阶段                                  │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  10. 复制 .espdl 模型到 main/models/                                   │
│                                                                        │
│  11. 编译烧录                                                           │
│      idf.py build flash monitor                                       │
│                                                                        │
│  12. ESP32离线运行，微信小程序控制                                      │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 软件架构

### ESP32-S3 固件

基于 ESP-IDF v5.3.1 + ESP-DL 框架实现：

- **摄像头驱动**: esp_camera, QQVGA (160x120) 灰度
- **WiFi**: AP 模式, TCP 命令通道 + UDP 视频流
- **电机控制**: LEDC PWM + GPIO 方向控制
- **编码器**: PCNT 脉冲计数
- **电池监测**: ADC 电压采样
- **深度学习**: ESP-DL 模型推理

### 微信小程序

功能模块：

| 模块 | 功能 |
|------|------|
| 连接控制 | 连接ESP32热点，控制机器人移动 |
| 实时预览 | UDP接收并显示视频流 |
| 数据采集 | 采集图像和编码器数据保存到本地 |
| 图表保存 | 导出编码器数据柱状图到相册 |

### Python 训练工具

| 脚本 | 功能 |
|------|------|
| `train_teacher.py` | 训练教师模型 (高精度) |
| `train_student.py` | 知识蒸馏训练学生模型 |
| `quantize_onnx_model.py` | ONNX 量化 (INT8) |
| `label_tool.py` | 数据标注和可视化 |
| `capture_img_client.py` | PC端图像采集客户端 |
| `tools.py` | 模型格式转换工具 |

---

## 快速开始

### 1. 环境准备

```bash
# ESP-IDF
E:\aishuai\Espressif\frameworks\esp-idf-v5.3.1

# ESP-DL
E:\aishuai\esp-dl\esp-dl

# Python依赖
pip install torch onnx onnxruntime numpy opencv-python pillow
```

### 2. 编译烧录

```bash
cd E:\AICleanBot

# 设置环境
call %IDF_PATH%\export.bat

# 编译
idf.py build

# 烧录
idf.py flash

# 串口监视
idf.py monitor
```

### 3. 模型部署

```bash
# 1. 训练模型
python py_scripts/net/train_student.py

# 2. 转换格式
python py_scripts/utils/tools.py export_pth_to_onnx

# 3. 量化
python py_scripts/net/quantize_onnx_model.py

# 4. 复制模型到 main/models/
# 5. 重新编译烧录
```

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 嵌入式 | ESP-IDF v5.3.1, ESP-DL, FreeRTOS |
| 深度学习 | PyTorch, ONNX, INT8 量化 |
| 通信 | WiFi STA/AP, TCP, UDP |
| 控制端 | 微信小程序 (WXML/WXSS/JS) |
| 工具 | Python, OpenCV |

---

## 项目成员

- **硬件**: ESP32-S3 + ESP32-CAM + TB6612FNG + JGA25-370
- **固件**: C++ (ESP-IDF)
- **小程序**: JavaScript (微信小程序)
- **训练**: Python (PyTorch)


