# Open Genjutsu

版本发布、审批、固定镜像 digest 的部署及回滚流程：[发布指南（韩语）](docs/release-process.ko.md)。

[한국어](README.md) · [English](README.en.md) · [简体中文](README.zh-CN.md)

**一个将原视频动作转移到新角色和场景的自托管视频制作平台。** 在浏览器中组合模型和提示词，跟踪生成任务，并下载完成的视频。

## 主要功能

- 连接原视频、参考图像、场景分析、提示词设计、动作迁移、编辑和输出节点。
- 为每个节点独立配置 API 提供商、模型 ID、提示词和生成参数。
- 按账户保存项目和媒体，检测版本冲突，并导入或导出工作流 JSON。
- 查看任务和节点结果，请求取消，下载视频，并管理存储的媒体。
- 通过 Temporal 在 API 重启后继续启动已保存的任务，在 Worker 重启后继续查询同一个提供商任务。
- 创建团队账户，加密保存 API 密钥，并将 Custom/GPU 密钥绑定到指定 API 地址。

## 安装

需要 Docker Engine、Docker Compose v2 和 Python 3。在已检出的仓库目录运行：

```bash
python3 scripts/configure.py
docker compose up -d --build
docker compose ps
```

打开 `http://localhost:8000`，使用 `.env` 中生成的管理员账户登录。在本地确认邮箱和初始密码，妥善保管该文件。登录后通过 **API 키** 菜单注册提供商密钥。Web 界面目前使用韩语。

公开访问需要 HTTPS。配置 DNS 和 `.env`：

```dotenv
GENJUTSU_DOMAIN=studio.example.com
GENJUTSU_PUBLIC_URL=https://studio.example.com
GENJUTSU_SECURE_COOKIES=true
```

```bash
docker compose --profile tls up -d --build
```

Caddy 提供 HTTPS。外部视频提供商必须能够通过公开地址读取带签名的输入媒体 URL。默认 API 端口仅绑定到本机 loopback；数据库和 Temporal 端口不对外公开。

## 制作视频

1. 在新项目中上传原视频和参考图像。
2. 选择动作模型和参数。默认工作流使用 Wan-Animate 和 FFmpeg 输出。
3. 按需添加分析、提示词或编辑节点，通过节点的提供商输入 JSON 设置模型选项。
4. 打开 **실행 계획**，查看服务器校验结果，确认付费 API 步骤后点击 **생성 시작**。
5. 在 **작업 내역** 中查看进度并下载结果。输出步骤合并原始音频并编码为 MP4。

Wan-Animate 不接受自由提示词，因此默认项目不包含无法影响视频结果的付费语言模型步骤。需要提示词控制时，使用 VACE 或兼容的模型服务器。新增语言模型节点默认推荐 Dolphin，也可输入其他模型 ID。

## 提供商支持

| 提供商 | 用途 |
| --- | --- |
| OpenRouter / OpenAI 兼容 Custom | 抽样帧分析和提示词生成 |
| fal | Wan-Animate move/replace、Wan VACE、Kling v3 Motion Control |
| Replicate | 使用模型专属输入 JSON 的 prediction API |
| Custom / GPU API | 实现异步任务协议的模型服务器 |
| Local | 媒体输入、FFmpeg 编码和原始音频合成 |

管理员需批准 Custom/GPU API 地址和结果 CDN 域名。Replicate 输入字段必须符合所选模型的 schema。模型可用性、费用和使用政策由提供商决定。本部署不包含 GPU 模型推理服务器和蒙版绘制界面。

## 运维

默认限制为每个上传文件 128MB、视频 30 秒、每用户存储 2GB、两个同时进行的任务，以及每次生成最多四个付费步骤。参阅 `.env.example`，并在提供商账户中设置费用上限。

提交响应丢失的任务进入人工核查，不会自动重复付费请求。管理员确认提供商任务 ID 后可继续查询，或在确认外部执行和计费后关闭任务。取消请求不意味着退款。

```bash
curl -fsS http://localhost:8000/api/readyz
docker compose logs --tail=100 api worker
bash scripts/backup.sh
```

在没有活动任务的维护时间执行备份。本配置部署在单台主机上，主机故障恢复需要同时备份两个数据库、媒体和加密密钥。

详细文档目前为韩语：

- [部署、备份、恢复与升级](docs/operations.ko.md)
- [模型输入与 Custom/GPU API 协议](docs/provider-contract.ko.md)
- [服务验证结果与范围](docs/service-validation.ko.md)
- [模型研究](docs/genjutsu-research-and-plan.ko.md)

## 开发与验证

前端需要 Node.js 22.12 及以上，后端使用 Python 3.12。`npm run dev` 连接本地运行中的 API；`npm run dev:editor` 运行离线编辑器。

```bash
npm ci
npm test
npm run build
npm run test:e2e
npm run test:service
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
PYTHONPATH=backend .venv/bin/pytest backend/tests -m 'not integration'
```

设置 `GENJUTSU_TEST_TEMPORAL_ADDRESS` 可运行真实 Temporal 集成测试。仅在可丢弃的测试部署上通过 `GENJUTSU_TEST_COMPOSE_STACK=1` 启用容器重启测试。外部付费提供商测试使用模拟服务；真实模型的生成质量和计费需通过运营账户另行验证。
