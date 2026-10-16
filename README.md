# Open Genjutsu

[한국어](README.md) · [English](README.en.md) · [简体中文](README.zh-CN.md)

**원본 영상의 움직임을 새로운 캐릭터와 장면으로 만드는 자체 호스팅 영상 작업 플랫폼입니다.** 브라우저에서 모델과 프롬프트를 조합하고, 생성 진행 상황을 확인하며, 완성된 영상을 내려받으세요.

## 주요 기능

- **노드 기반 제작** — 원본 영상, 참조 이미지, 장면 분석, 프롬프트 작성, 모션 전이, 영역 편집과 결과 내보내기 노드를 연결합니다.
- **OpenRouter 모델 조합** — OpenRouter의 텍스트·이미지·영상 모델을 노드마다 고르고 모델·프롬프트·모델 옵션을 바꿉니다.
- **프로젝트와 미디어 저장** — 계정별 서버 저장, 버전 충돌 검사, JSON 교환과 미디어 관리로 작업을 이어갑니다.
- **작업 추적과 결과 다운로드** — 대기·생성·완료·확인 대기 상태, 단계별 텍스트와 영상 결과, 취소 요청을 제공합니다.
- **Temporal 실행** — API 재시작 후 접수된 작업을 이어 시작하고, Worker 재시작 후 같은 생성 요청 ID를 계속 조회합니다.
- **팀 계정과 API 키 관리** — 관리자 계정 발급, 계정별 접근 제어, 암호화된 OpenRouter 키 저장을 지원합니다.
- **모델별 제작 설정** — Genjutsu 템플릿(MiniMax H3 모션 전이), 노드 종류별 추천 모델, 모델이 지원하는 해상도·길이·화면 비율·참조 방식을 고르는 모델 옵션을 제공합니다. 고급 옵션(JSON)과 직접 지정한 OpenRouter 모델도 사용할 수 있습니다.
- **운영 현황** — 관리자가 대기 시간, 완료 시간 P95, 미디어·디스크 사용량과 공급자 확인 대기 작업을 조회하고 기존 생성 요청 ID로 복구합니다.

## 설치

Docker Engine, Docker Compose v2, Python 3이 필요합니다. 저장소를 체크아웃한 디렉터리에서 실행하세요.

```bash
python3 scripts/configure.py
docker compose up -d --build
docker compose ps
```

브라우저에서 `http://localhost:8000`을 열고 `.env`에 생성된 관리자 계정으로 로그인합니다. `.env`에서 이메일·초기 비밀번호를 확인하고 파일을 안전하게 보관하세요. OpenRouter API 키는 로그인 후 **API 키** 메뉴에서 등록합니다.

먼저 **새 프로젝트 템플릿 → 로컬 영상 테스트**로 업로드·Temporal 실행·MP4 다운로드를 확인하세요. localhost에서도 OpenRouter 키로 분석·프롬프트·이미지 생성과 이미지 기반 영상 생성을 실행할 수 있습니다. **원본 영상을 쓰는 모션 전이·영역 편집에는 공개 HTTPS 주소가 필요합니다.** OpenRouter가 모델에 보낼 영상을 공개 HTTPS URL로만 받기 때문입니다. [로컬 테스트 가이드](docs/local-testing.ko.md)에 설치와 총 $10 이내 모델 시험 절차를 설명합니다.

공개 운영에는 HTTPS가 필요합니다. `.env`에 실제 도메인과 공개 주소를 설정하세요.

```dotenv
GENJUTSU_DOMAIN=studio.example.com
GENJUTSU_PUBLIC_URL=https://studio.example.com
GENJUTSU_SECURE_COOKIES=true
```

```bash
docker compose --profile tls up -d --build
```

Caddy가 HTTPS를 제공합니다. 공개 HTTPS 주소에서는 OpenRouter가 만료되는 서명 URL로 입력 미디어를 읽으므로 이 주소에 접근할 수 있어야 합니다. 기본 API 포트는 loopback에만 바인딩하며 DB·Temporal 포트는 공개하지 않습니다.

고정 IP나 공유기 포트 개방 없이 연결하려면 [Cloudflare Tunnel 스테이징 가이드](docs/cloudflare-staging.ko.md)를 사용하세요. Docker가 실행되는 PC 또는 VPS와 도메인이 필요합니다.

## 영상 만들기

1. 새 프로젝트에서 원본 영상과 참조 이미지를 업로드합니다.
2. **Genjutsu** 템플릿으로 시작해 모션 전이 노드의 모델과 모델 옵션을 조절합니다. 기본 프로젝트는 원본 영상 + 참조 이미지 → 모션 전이(MiniMax H3) → 결과 내보내기(FFmpeg)로 구성됩니다. Seedance 2.5는 실제 인물로 보이는 원본 영상을 거절해 모션 전이 기본값에서 뺐습니다.
3. 필요한 경우 장면 분석·프롬프트 작성·영역 편집 노드를 추가합니다. 노드 설정의 **모델 옵션**에서 모델마다 다른 항목을 고르고, **고급 옵션(JSON)**에서 직접 고칠 수도 있습니다.
4. **실행 전 확인**에서 단계·예상 비용·오류와 경고를 확인하고, 유료 API 단계가 있으면 비용 발생에 동의한 뒤 **생성 시작**을 누릅니다.
5. **작업 내역**에서 진행 상황을 보고 결과물을 내려받습니다. 결과 내보내기는 연결된 이미지나 영상 하나를 결과물로 저장합니다. 영상은 노드의 **오디오** 설정(원본 오디오·생성 오디오·무음)에 따라 소리를 넣어 MP4로 인코딩합니다. 오디오를 고르지 않으면 연결 흐름에 원본 영상이 있을 때 원본 오디오, 없을 때 생성 오디오를 씁니다.

모션 전이 노드는 참조 이미지를 **인물·스타일 참조**로 원본 영상과 함께 보내고, 참조 인물이 원본의 동작·카메라·타이밍을 따르도록 하는 기본 프롬프트를 사용합니다. 기본 프로젝트에는 유료 언어 모델 단계를 넣지 않았습니다. 장면 분석·프롬프트 작성 노드를 추가하면 Qwen3 VL·Dolphin이 기본 모델이며 다른 모델 ID로 교체할 수 있습니다.

**추천 모델**은 선택한 노드 종류의 모델만 보여줍니다. OpenRouter 모델 ID 입력란은 서버가 6시간마다 갱신하는 OpenRouter 공개 모델 목록(텍스트·이미지·영상 약 650개)에서 노드에 맞는 모델을 제안합니다. **이미지 생성** 노드로 참조 이미지를 만들고, 모션 전이·영역 편집 노드에서 OpenRouter 영상 모델을 선택할 수 있습니다. OpenRouter 영상 생성 요청은 시작 후 취소할 수 없으며, 원본 영상을 모델에 보내려면 공개 HTTPS 주소가 필요합니다. 실행 전 확인은 초당 가격 모델(MiniMax H3, Wan, Kling, Veo, FLUX.3 등)의 예상 비용을 보여주며 Seedance처럼 토큰 단가인 모델은 예상 불가로 표시합니다. 작업 내역은 공급자가 보고한 실제 비용을 보여줍니다.

## 연결 가능한 공급자

| 공급자 | 용도 |
| --- | --- |
| OpenRouter 텍스트 | 샘플 프레임 또는 영상 전체 분석, 프롬프트 작성 |
| OpenRouter 이미지·영상 | 참조 이미지 생성, 원본 영상·참조 이미지를 쓰는 모션 전이·영역 편집, 이미지 기반 영상 생성 |
| Local | 입력 미디어, FFmpeg 결과 내보내기(이미지·영상 결과물, 오디오 선택) |

생성 단계는 OpenRouter만 사용하며 공급자는 노드 종류별로 고정됩니다. 추천 영상 모델 중 MiniMax H3, Seedance 2.5·2.0·2.0 Fast, FLUX.3 Video, Runway Aleph 2.0(영역 편집)은 원본 영상을 받고, Veo 3.1, Kling v3.0 Pro, Wan 3.0, Grok Imagine Video 1.5는 이미지 기반 영상만 생성합니다. 실제 시험에서 Seedance 2.5는 실제 인물로 보이는 원본 영상을 거절했고, FLUX.3 Video는 원본 영상과 참조 이미지를 한 요청에 받지 않아 모션 전이에 쓸 수 없었습니다. 목록 밖 OpenRouter 모델도 ID로 입력할 수 있습니다. 모델 가용성·요금·사용 정책은 OpenRouter와 모델 공급자를 따릅니다. 이전에 fal·Replicate·GPU·Custom 노드로 저장한 프로젝트는 해당 단계의 OpenRouter 기본 모델로 열립니다.

## 운영

기본 한도는 파일당 128MB, 영상 30초, 사용자 저장 공간 2GB, 동시 작업 2개, 작업당 유료 단계 4개입니다. 설정값은 `.env.example`을 참고하세요. 달러 단위 지출 제한은 공급자 계정에도 설정하세요.

제출 응답을 잃은 작업은 중복 과금을 막기 위해 자동 재제출하지 않고 **공급자 확인 대기**로 남깁니다. 운영자가 실제 생성 요청 ID나 비용 처리를 확인한 후 복구·종료합니다. 취소 요청은 외부 취소 완료나 환불과 구분합니다.

```bash
curl -fsS http://localhost:8000/api/readyz
docker compose logs --tail=100 api worker
bash scripts/backup.sh
```

백업은 활성 작업이 없는 유지보수 시간에 실행합니다. 이 배포는 단일 호스트용이며, 호스트 장애 복구에는 DB·미디어·암호화 키를 함께 보관한 백업이 필요합니다.

- [배포·백업·복구·업데이트 운영 가이드](docs/operations.ko.md)
- [버전 관리·릴리스 승인·digest 고정 배포](docs/release-process.ko.md)
- [Cloudflare Tunnel로 HTTPS 연결](docs/cloudflare-staging.ko.md)
- [비용 상한을 정한 실제 모델 평가](docs/model-evaluation.ko.md)
- [베타 운영과 출시 기준](docs/beta-checklist.ko.md)
- [모델 옵션과 OpenRouter 연결 계약](docs/provider-contract.ko.md)
- [서비스 검증 결과와 범위](docs/service-validation.ko.md)
- [모델 조사와 선택 근거](docs/genjutsu-research-and-plan.ko.md)

## 개발과 검증

프런트엔드는 Node.js 22.12 이상, 서버는 Python 3.12를 사용합니다. `npm run dev`는 실행 중인 로컬 API에 연결하고, `npm run dev:editor`는 오프라인 편집기를 실행합니다.

```bash
npm ci
npm test
npm run build
npm run test:e2e             # 오프라인 편집기 브라우저 회귀 검사
npm run test:service         # 실행 중인 Compose 서비스의 데스크톱·모바일 검사
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
PYTHONPATH=backend .venv/bin/pytest backend/tests -m 'not integration'
```

실제 Temporal 통합 검사는 `GENJUTSU_TEST_TEMPORAL_ADDRESS`를 지정합니다. 컨테이너 재시작 검사는 폐기 가능한 테스트 스택에서만 `GENJUTSU_TEST_COMPOSE_STACK=1`로 실행합니다. 외부 유료 공급자 테스트는 가짜 공급자로 수행하며, 실제 모델의 생성 품질과 과금은 운영 계정의 별도 검증이 필요합니다.
