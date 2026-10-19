# Open Genjutsu

版本发布、审批、固定镜像 digest 的部署及回滚流程：[发布指南（韩语）](docs/release-process.ko.md)。

[한국어](README.md) · [English](README.en.md) · [简体中文](README.zh-CN.md)

**一个将原视频动作转移到新角色和场景的自托管视频制作平台。** 在浏览器中组合模型和提示词，跟踪生成作业，并下载完成的视频。

## 主要功能

- 连接原视频、参考图像、场景分析、提示词编写、动作迁移、区域编辑和最终输出节点。
- 为每个节点选择 OpenRouter 文本、图像和视频模型，并独立配置模型 ID、提示词和模型选项。
- 按账户保存项目和媒体，检测版本冲突，并导入或导出项目 JSON。
- 查看作业和节点结果，请求取消，下载视频，并管理存储的媒体。
- 通过 Temporal 在 API 重启后继续启动已保存的作业，在 Worker 重启后继续查询同一个生成请求。
- 创建团队账户，并为每个账户加密保存 OpenRouter API 密钥。
- 使用 Genjutsu 模板（MiniMax H3 动作迁移）、按节点类型推荐的模型和模型选项，同时支持其他 OpenRouter 模型 ID 和高级选项（JSON）。
- 管理员可查看排队时间、最近完成时间 P95、媒体和磁盘用量，并使用已有的生成请求 ID 恢复待确认作业。

## 安装

无需开放入站端口的 HTTPS 接入方式见 [Cloudflare Tunnel 指南（韩语）](docs/cloudflare-staging.ko.md)。仍需运行 Docker 的主机和域名。

需要 Docker Engine、Docker Compose v2 和 Python 3。在已检出的仓库目录运行：

```bash
python3 scripts/configure.py
docker compose up -d --build
docker compose ps
```

打开 `http://localhost:8000`，使用 `.env` 中生成的管理员账户登录。在本地确认邮箱和初始密码，妥善保管该文件。登录后通过 **API 키** 菜单注册 OpenRouter 密钥。Web 界面目前使用韩语。

先选择 **새 프로젝트 템플릿 → 로컬 영상 테스트**，免费检查上传、Temporal 执行和 MP4 下载。在 localhost 上也可以用 OpenRouter 密钥运行分析、提示词、图像生成和基于图像的视频生成。**使用原视频的动作迁移和区域编辑需要公开 HTTPS 地址**，因为 OpenRouter 只接受公开 HTTPS URL 形式的视频。安装和总额 $10 的评估步骤见[本地测试指南（韩语）](docs/local-testing.ko.md)；请在 OpenRouter 账户设置支出上限。

公开访问需要 HTTPS。配置 DNS 和 `.env`：

```dotenv
GENJUTSU_DOMAIN=studio.example.com
GENJUTSU_PUBLIC_URL=https://studio.example.com
GENJUTSU_SECURE_COOKIES=true
```

```bash
docker compose --profile tls up -d --build
```

Caddy 提供 HTTPS。使用公开 HTTPS 地址时，OpenRouter 通过会过期的签名 URL 读取输入媒体，因此需要能够访问该地址。默认 API 端口仅绑定到本机 loopback；数据库和 Temporal 端口不对外公开。

## 制作视频

1. 在新项目中上传原视频和参考图像。可在原视频节点一边预览一边以 0.1 秒精度设置使用的**区间**（**구간**，例如 10 秒视频中的 3–8 秒）；未设置时使用整个视频。接收原视频的动作迁移和区域编辑会以覆盖区间的最短模型时长生成，再裁剪为区间长度；原始音频也只使用该区间。区间超过模型最大时长时，会分成等长的片段（**조각**）依次生成并拼接为一个视频（**나눠 생성**）。从第二个片段起，会把上一片段的最后一帧作为参考图像一并发送以衔接边界。某个片段失败时，会保留已完成片段拼接的部分视频（**부분 영상**）。
2. 从 **Genjutsu** 模板（原视频 + 参考图像 → 动作迁移 → 最终输出）开始，调整动作迁移节点的模型和模型选项。默认项目使用 MiniMax H3 动作迁移和 FFmpeg 最终输出。Seedance 2.5 会拒绝看起来是真人的原视频，因此不再作为动作迁移默认模型。
3. 按需添加场景分析、提示词编写或区域编辑节点。在节点的模型选项（**모델 옵션**）中选择模型专用设置，也可以在 **고급 옵션(JSON)** 中直接修改 JSON。
4. 打开运行前检查（**실행 전 확인**），查看步骤、预计费用、错误和警告，确认付费 API 步骤后点击 **생성 시작**。
5. 在作业记录（**작업 내역**）中查看进度，并直接播放或下载结果。作业记录默认只显示当前打开项目的作业，可在**보기**中切换为所有项目。画布上的最终输出节点也会显示最新结果，并可在节点设置中播放。最终输出节点将连接的一个图像或视频保存为结果。视频按节点的**音频**设置（原始音频、生成音频或静音）编码为 MP4；未设置时，若流程上游有原视频则使用原始音频，否则使用生成音频。

动作迁移节点将参考图像作为人物和风格参考（**인물·스타일 참조**），与原视频一起发送，并使用默认提示词让参考人物执行原视频的动作、镜头运动和节奏。默认项目不包含付费语言模型步骤。新增场景分析和提示词编写节点默认使用 Qwen3 VL 和 Dolphin，也可输入其他模型 ID。

**추천 모델** 列表只显示所选节点类型的模型。OpenRouter 模型 ID 输入框会根据节点类型，从服务器每 6 小时刷新的 OpenRouter 公开模型目录（约 650 个文本、图像和视频模型）中给出建议。可使用 **图像生成** 节点制作参考图像，并在动作迁移或区域编辑节点中选择 OpenRouter 视频模型。OpenRouter 视频生成请求开始后无法取消；将原视频发送给模型需要公开 HTTPS 地址。运行前检查会显示按秒计价模型（如 MiniMax H3、Wan、Kling、Veo、FLUX.3）的预计费用，Seedance 等按 token 计价的模型显示为无法估算；作业记录显示提供商报告的实际费用。

## 提供商支持

| 提供商 | 用途 |
| --- | --- |
| OpenRouter 文本 | 抽样帧或完整视频分析、提示词生成 |
| OpenRouter 图像与视频 | 生成参考图像，使用原视频和参考图像的动作迁移与区域编辑，基于图像生成视频 |
| Local | 媒体输入，以及最终输出（FFmpeg；图像或视频结果，音频选择） |

生成步骤只使用 OpenRouter，提供商按节点类型固定。推荐视频模型中，MiniMax H3、Seedance 2.5、Seedance 2.0、Seedance 2.0 Fast、FLUX.3 Video 和 Runway Aleph 2.0（区域编辑）可以接收原视频；Veo 3.1、Kling v3.0 Pro、Wan 3.0 和 Grok Imagine Video 1.5 只能基于图像生成视频。实际测试中，Seedance 2.5 拒绝了看起来是真人的原视频；FLUX.3 Video 不能在同一请求中同时接收原视频和参考图像，因此无法用于动作迁移。其他 OpenRouter 模型仍可通过 ID 输入。模型可用性、费用和使用政策由 OpenRouter 和模型提供商决定。此前使用 fal、Replicate、GPU 或 Custom 节点保存的项目，会以对应步骤的 OpenRouter 默认模型打开。

## 运维

默认限制为每个上传文件 512MB、视频 120 秒、每用户存储 2GB、两个同时进行的作业，以及每个作业最多四个付费步骤。参阅 `.env.example`，并在提供商账户中设置费用上限。

提交响应丢失的作业进入人工核查，不会自动重复付费请求。管理员确认生成请求 ID 后可继续查询，或在确认外部执行和计费后关闭作业。取消请求不意味着退款。

```bash
curl -fsS http://localhost:8000/api/readyz
docker compose logs --tail=100 api worker
bash scripts/backup.sh
```

在没有活动作业的维护时间执行备份。本配置部署在单台主机上，主机故障恢复需要同时备份两个数据库、媒体和加密密钥。

详细文档目前为韩语：

- [部署、备份、恢复与升级](docs/operations.ko.md)
- [模型选项与 OpenRouter 接入协议](docs/provider-contract.ko.md)
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
