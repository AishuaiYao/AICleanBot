## 这个 PR 做了什么

<!-- 一句话说明 -->

## 为什么

<!-- 关联 issue：Fixes #123 -->

## 改动范围

- [ ] 固件 `main/`
- [ ] Python 训练 `py_scripts/net/`
- [ ] Python 工具 `py_scripts/utils/`
- [ ] 硬件资料 `hardware/`
- [ ] 文档 / 官网 `docs/`
- [ ] 小程序 `smartcat/`（子模块，请到对应仓库提 PR）

## 怎么验证的

<!-- 贴关键日志、截图或命令输出，不要只写"测试通过" -->

```bash

```

## 自检

- [ ] 固件改动能通过 `idf.py build`
- [ ] Python 改动通过 `python -m py_compile`
- [ ] 新增依赖已同步到 `requirements.txt`
- [ ] 没有引入硬编码的绝对路径（`E:\...`、`C:\Users\...`）
- [ ] 改了引脚/协议的话，README 或 `hardware/README.md` 已同步
- [ ] 没有提交模型权重、数据集、构建产物

## 破坏性变更

<!-- 改了引脚定义、TCP 命令、模型输入尺寸等对外契约？在这里写清迁移方式；没有则填「无」 -->
