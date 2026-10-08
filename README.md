# Open Genjutsu

[한국어](README.md) · [English](README.en.md) · [简体中文](README.zh-CN.md)

**원본 영상의 움직임을 새로운 캐릭터와 장면으로 만드는 자체 호스팅 영상 작업 플랫폼입니다.** 브라우저에서 모델과 프롬프트를 조합하고, 생성 진행 상황을 확인하며, 완성된 영상을 내려받으세요.

## 주요 기능

- **노드 기반 제작** — 원본 영상, 참조 이미지, 장면 분석, 프롬프트 설계, 모션 전이, 편집과 출력 단계를 연결합니다.
- **여러 모델 조합** — OpenRouter, fal, Replicate와 사용자 지정 API를 연결하고 노드마다 모델·프롬프트·생성 옵션을 바꿉니다.
- **프로젝트와 미디어 저장** — 계정별 서버 저장, 버전 충돌 검사, JSON 교환과 미디어 관리로 작업을 이어갑니다.
- **작업 추적과 결과 다운로드** — 대기·생성·완료·확인 대기 상태, 단계별 텍스트와 영상 결과, 취소 요청을 제공합니다.
- **Temporal 실행** — API 재시작 후 접수된 작업을 이어 시작하고, Worker 재시작 후 같은 공급자 접수 ID를 계속 조회합니다.
- **팀 계정과 API 키 관리** — 관리자 계정 발급, 계정별 접근 제어, 암호화된 키 저장과 Custom/GPU 주소별 키 연결을 지원합니다.
- **모델별 제작 설정** — Wan·Kling·VACE 프로젝트 템플릿과 Kling 방향·오디오, VACE 작업·추론·마스크 입력 폼을 제공합니다. 고급 입력 JSON과 직접 지정한 모델도 사용할 수 있습니다.
- **운영 현황** — 관리자가 대기 시간, 완료 시간 P95, 미디어·디스크 사용량과 공급자 확인 대기 작업을 조회하고 기존 접수 ID로 복구합니다.

## 설치

Docker Engine, Docker Compose v2, Python 3이 필요합니다. 저장소를 체크아웃한 디렉터리에서 실행하세요.

```bash
python3 scripts/configure.py
docker compose up -d --build
docker compose ps
```

브라우저에서 `http://localhost:8000`을 열고 `.env`에 생성된 관리자 계정으로 로그인합니다. `.env`에서 이메일·초기 비밀번호를 확인하고 파일을 안전하게 보관하세요. API 키는 로그인 후 **API 키** 메뉴에서 등록합니다.

먼저 **새 프로젝트 템플릿 → 로컬 영상 테스트 · 무료**로 업로드·Temporal 실행·MP4 다운로드를 확인하세요. 기본 `GENJUTSU_MEDIA_DELIVERY=upload` 설정은 fal/Replicate 파일 API를 사용해 **도메인 없이 실제 영상 모델도 연결**합니다. [로컬 테스트 가이드](docs/local-testing.ko.md)에 설치와 총 $10 이내 모델 비교 절차를 설명합니다. 기존 `.env`에는 이 설정을 직접 추가하세요.

공개 운영에는 HTTPS가 필요합니다. `.env`에 실제 도메인과 공개 주소를 설정하세요.

```dotenv
GENJUTSU_DOMAIN=studio.example.com
GENJUTSU_PUBLIC_URL=https://studio.example.com
GENJUTSU_SECURE_COOKIES=true
```

```bash
docker compose --profile tls up -d --build
```

Caddy가 HTTPS를 제공합니다. `GENJUTSU_MEDIA_DELIVERY=signed` 또는 Custom/GPU 영상 경로에서는 공급자가 공개 입력 URL에 접근할 수 있어야 합니다. 기본 API 포트는 loopback에만 바인딩하며 DB·Temporal 포트는 공개하지 않습니다.

고정 IP나 공유기 포트 개방 없이 연결하려면 [Cloudflare Tunnel 스테이징 가이드](docs/cloudflare-staging.ko.md)를 사용하세요. Docker가 실행되는 PC 또는 VPS와 도메인이 필요합니다.

## 영상 만들기

1. 새 프로젝트에서 원본 영상과 참조 이미지를 업로드합니다.
2. Wan·Kling·VACE 중 새 프로젝트 템플릿을 고르고 모션 노드의 모델과 옵션을 조절합니다. 기본 프로젝트는 Wan-Animate 모션 전이와 FFmpeg 출력으로 구성됩니다.
3. 필요한 경우 분석·프롬프트·편집 노드를 추가합니다. 노드 설정의 **공급자 입력 JSON**에서 모델별 옵션도 지정할 수 있습니다.
4. **실행 계획**에서 서버 검증 결과를 확인하고, 유료 API 단계가 있으면 비용 발생에 동의한 뒤 **생성 시작**을 누릅니다.
5. **작업 내역**에서 진행 상황을 보고 결과를 다운로드합니다. 출력 단계는 원본 오디오를 결합해 MP4로 저장합니다.

Wan-Animate는 자유 프롬프트를 받지 않습니다. 기본 프로젝트에는 결과에 영향을 주지 않는 유료 언어 모델 단계를 넣지 않았습니다. 프롬프트 제어는 VACE 또는 해당 입력을 지원하는 모델 서버를 사용하세요. 언어 모델 노드를 추가하면 Dolphin이 기본 후보이며 다른 모델 ID로 교체할 수 있습니다.

## 연결 가능한 공급자

| 공급자 | 용도 |
| --- | --- |
| OpenRouter / OpenAI 호환 Custom | 샘플 프레임 분석과 프롬프트 작성 |
| fal | Wan-Animate move/replace, Wan VACE, Kling v3 Motion Control |
| Replicate | 모델별 입력 JSON을 사용하는 prediction 작업 |
| Custom / GPU API | 비동기 작업 계약을 구현한 모델 서버 |
| Local | 입력 미디어와 FFmpeg 출력·오디오 결합 |

Custom/GPU 주소와 결과 CDN은 운영자가 먼저 허용해야 합니다. Replicate 입력 필드는 해당 모델 schema에 맞게 지정합니다. 모델 가용성·요금·사용 정책은 공급자 설정을 따릅니다. GPU 추론 서버와 마스크 페인팅 UI는 이 배포에 포함되지 않습니다.

## 운영

기본 한도는 파일당 128MB, 영상 30초, 사용자 저장 공간 2GB, 동시 작업 2개, 실행당 유료 단계 4개입니다. 설정값은 `.env.example`을 참고하세요. 달러 단위 지출 제한은 공급자 계정에도 설정하세요.

제출 응답을 잃은 작업은 중복 과금을 막기 위해 자동 재제출하지 않고 **공급자 확인 대기**로 남깁니다. 운영자가 실제 접수 ID나 비용 처리를 확인한 후 복구·종료합니다. 취소 요청은 외부 취소 완료나 환불과 구분합니다.

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
- [모델 입력과 Custom/GPU API 계약](docs/provider-contract.ko.md)
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
