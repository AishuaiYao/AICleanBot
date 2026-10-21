# 贡献指南

感谢你愿意为 AICleanBot 做贡献。本项目包含嵌入式固件、微信小程序、Python 训练工具三部分，改动前请先确认你要改的是哪一层。

## 开发环境

| 层级 | 需要安装 |
|------|----------|
| 固件 (`main/`) | ESP-IDF **v5.4.x**（Windows 用官方离线安装包自动配好工具链） |
| 上位机 (`smartcat/`) | 微信开发者工具（稳定版） |
| 训练工具 (`py_scripts/`) | Python 3.10+，依赖见 `requirements.txt` |

克隆时**必须带子模块**，否则 `smartcat/` 会是空目录：

```bash
git clone --recurse-submodules https://github.com/AishuaiYao/AICleanBot.git
# 已克隆过的：
git submodule update --init --recursive
```

## 提交 Issue

提 Bug 请附带上这些信息，否则很难复现：

- 硬件：主控型号、摄像头、电机驱动、电池电压
- 软件：ESP-IDF 版本（`idf.py --version`）、Python 版本、commit hash
- 复现步骤与串口日志（`idf.py monitor` 输出，用 \`\`\` 代码块包裹）

## Pull Request 流程

1. Fork 本仓库，从 `main` 切分支，命名建议 `feat/xxx`、`fix/xxx`、`docs/xxx`
2. 保持一次 PR 只做一件事，混在一起会拖慢 review
3. 提交前自检：
   - 固件能编译通过：`idf.py build`
   - Python 脚本改动后至少 `python -m py_compile` 通过
   - 新增依赖同步更新 `requirements.txt`
4. PR 描述里说清「改了什么 / 为什么改 / 怎么验证的」

## 代码约定

**固件（C/C++）**

- 引脚、WiFi 参数、PID 增益等**不要散布在逻辑代码里**，定义在文件顶部的 `#define` 区块，并加中文注释
- 日志统一用 `ESP_LOGx(TAG, ...)`，格式 `[模块] 内容`，便于用串口工具过滤
- 新增外设请同步更新 `README.md` 的引脚定义表

**Python**

- 路径**必须**用 `Path(__file__).resolve().parents[n]` 推导，**禁止**写死任何绝对路径（尤其是 `E:\...`）
- 新增脚本请在文件头部 docstring 写清：部署位置（PC / ESP32）、功能、配套脚本
- 随机种子固定为 `SEED = 42`，保证实验可复现

**微信小程序（smartcat 子模块）**

- smartcat 是独立仓库，改动请直接到 https://github.com/AishuaiYao/smartcat 提 PR
- 主仓库只需更新子模块指针

## 硬件改动

如果你做出了不同接线的版本，欢迎提硬件适配 PR，但请：

- 引脚改动通过 `#define` 切换，不要直接删改现有定义
- 在 README 的「硬件清单」表格里标注你的版本

## License

你提交的代码默认以本项目相同的 [Apache-2.0](LICENSE) 许可发布。
