# Open Genjutsu

[한국어](README.ko.md) · [English](README.md) · [简体中文](README.zh-CN.md)

一个用于组合多种视频模型的节点式工作流工作室。每个节点都可以独立配置 API 提供商、模型 ID、提示词和生成参数。

## 快速开始

需要 Node.js 22.12 或更高版本。当前环境已使用 Node.js 24 验证。

```bash
npm ci
npm run dev
```

## Web 界面

- 添加节点、拖动布局、连接端口、复制、删除和撤销操作。
- 选择 OpenRouter、fal、Replicate、GPU Worker、Custom API 或 Local 提供商。
- 选择推荐模型，或输入自定义模型 ID 和 API 地址。
- 为每个节点独立编辑提示词、temperature、seed 和分辨率。
- 自动保存到浏览器存储，并导入或导出工作流 JSON。
- 拒绝循环连接、重复连接和无效 JSON；查看执行顺序及模型兼容性提示。
- 支持桌面和移动端编辑，以及当前会话中的媒体预览。

当前实现是**工作流编辑器和执行计划预览**。尚未接入 Temporal、身份验证、API 密钥管理和视频生成 API。执行计划按钮只校验并导出 JSON 计划，不会生成视频或产生 API 费用。请勿在界面或工作流 JSON 中填写 API 密钥。

媒体预览仅保存在当前浏览器会话中，不会上传到服务器。刷新后需要重新选择文件。浏览器存储仅属于当前浏览器和设备；迁移到其他环境时，请导出 JSON。

## 验证

```bash
npm test
npm run build
npm run test:e2e
```

`test:e2e` 先构建生产版本，再使用 Playwright 操作桌面和移动端 Chromium。如果存在 `/usr/bin/chromium`，会自动使用该程序。可以通过 `PLAYWRIGHT_CHROMIUM_EXECUTABLE` 指定其他可执行文件。如果没有系统 Chromium，请先运行 `npx playwright install chromium`。操作系统还需要安装浏览器所需的运行时依赖。

运行 `npm run test:e2e:report` 可打开 HTML 报告。失败测试的截图和 trace 保存在 `test-results/` 中。验证不会调用视频生成 API。

- [直接浏览器验证结果（韩语）](docs/browser-validation.ko.md)

## 设计

详细设计文档目前提供韩语版本。

- [模型研究与实现计划](docs/genjutsu-research-and-plan.ko.md)
- [基于 Temporal 的执行架构](docs/temporal-architecture.ko.md)
- [Web 编辑器数据与执行器集成](docs/web-studio.ko.md)
