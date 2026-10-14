# 로컬에서 테스트하기

Docker가 설치된 자신의 컴퓨터에서 웹 UI, 프로젝트 저장, Temporal 실행과 실제 OpenRouter 모델 API를 테스트합니다. 생성 단계는 OpenRouter 키 하나로 실행합니다. localhost에서는 분석·프롬프트·참조 이미지 생성과 이미지 기반 영상 생성이 동작합니다. 원본 영상을 참조하는 모션 전이·편집은 공개 HTTPS가 필요하므로 [Cloudflare Tunnel](cloudflare-staging.ko.md) 등으로 서비스를 공개해야 합니다.

## 시작

Docker Engine/Docker Desktop, Compose 2.24.4 이상, Git과 Python 3을 준비합니다.

```bash
git clone https://github.com/videorighter/open-genjutsu.git
cd open-genjutsu
```

기존 체크아웃에서는 작업 내용을 보존한 뒤 최신 코드를 받습니다. 저장소 디렉터리에서 아래 명령을 실행합니다. `.env`가 없다면 처음 한 번만 생성합니다. Windows에서는 설치 형태에 따라 `python3` 대신 `python` 또는 `py -3`을 사용합니다.

```bash
python3 scripts/configure.py
docker compose up -d --build --wait --wait-timeout 180
docker compose ps
```

이미 `.env`가 있으면 첫 명령은 건너뛰고 기존 키와 비밀번호를 유지합니다. 로컬 설정은 다음과 같습니다. 이전 버전의 `.env`에 남은 `GENJUTSU_MEDIA_DELIVERY`, `GENJUTSU_CUSTOM_API_URLS`, `GENJUTSU_UPLOAD_HOSTS` 값은 무시됩니다.

```dotenv
HTTP_PORT=8000
GENJUTSU_PUBLIC_URL=http://localhost:8000
GENJUTSU_SECURE_COOKIES=false
```

이 주소는 **Docker를 실행한 본인의 컴퓨터**에서 엽니다. 원격 개발 환경의 localhost는 자신의 PC에 자동 연결되지 않습니다. `.env`에서 관리자 이메일·비밀번호를 확인해 로그인합니다. API 포트는 127.0.0.1에만 연결하며 DB와 Temporal 포트는 외부에 공개하지 않습니다. `tls`·`tunnel` 프로필은 켜지 않습니다.

## 비용 없이 영상 처리 확인

1. 상단 **새 프로젝트 템플릿**에서 **로컬 영상 테스트 · 무료**를 선택하고 **새 프로젝트**를 누릅니다.
2. **원본 영상 → 결과 내보내기**의 두 노드가 나타납니다. 원본 노드에서 30초 이하 영상 파일을 업로드합니다. 기본 파일 상한은 128 MB입니다.
3. 미리보기를 확인하고 서버 저장 후 새로고침해도 파일과 설정이 남는지 확인합니다.
4. **실행 계획 → 생성 시작**을 누릅니다. 유료 모델 단계가 없어 API 키와 비용 동의가 필요하지 않습니다.
5. **작업 내역**에서 완료된 MP4를 내려받아 확인합니다. 원본에 오디오가 있으면 출력에도 포함됩니다.

이 템플릿은 Temporal과 FFmpeg의 업로드·처리·저장·다운로드 흐름을 확인합니다. AI 모션 전이는 **모션 전이 · OpenRouter** 템플릿을 사용합니다.

## 실제 모델 테스트: 총 $10 이내

1. 무료 영상 처리부터 성공하는지 확인합니다. 첫 AI 입력은 실제 움직임이 있는 **3~5초 영상 1개와 참조 이미지 1개**로 준비합니다. 같은 입력을 모델마다 비교합니다.
2. OpenRouter 계정에서 자동 충전을 끄고 키 지출 한도를 설정합니다. 승인된 총액은 **$10**이며, 앱의 비용 동의는 달러 한도를 강제하지 않습니다. 최대 청구액을 확정할 수 없는 요청은 보내지 않습니다.
3. **API 키**에서 OpenRouter 키를 등록합니다. 키를 채팅·프로젝트 JSON·Git에 넣지 않습니다.
4. localhost에서는 장면 분석·프롬프트 설계, 이미지 생성, 참조 이미지만 쓰는 이미지→영상 생성을 실행할 수 있습니다. 원본 영상을 모션 전이·편집 노드에 연결하면 실행 계획이 공개 HTTPS가 필요하다는 오류를 표시합니다. 아래 절을 따릅니다.
5. **실행 계획**의 오류와 경고를 확인합니다. Seedance처럼 토큰 단가인 모델은 예상 비용이 **예상 불가**로 표시됩니다. 현재 단가·길이·해상도·최소 청구 단위·실패 과금을 OpenRouter에서 확인한 뒤 비용 발생에 동의하고 한 번만 실행합니다.
6. 완료 결과, 작업 내역의 단계별 실제 비용과 OpenRouter 대시보드의 **실제 청구액**을 확인합니다. 남은 예산 안에서 다음 모델을 비교합니다.

이전 배분(OpenRouter $0.50, Wan $2.50, Kling $3, VACE $3, 예비 $1)은 fal 경로가 제거돼 적용하지 않습니다. 호출마다 최대 비용을 먼저 확인하고, 이미 청구된 금액과 진행 중인 호출의 최대 비용을 합해 $10을 넘지 않을 때만 실행합니다. 상세 기록·중단 기준은 [실제 모델 평가](model-evaluation.ko.md)를 따릅니다. 접수 여부가 불명확한 작업은 **공급자 확인 대기**로 남으며 새 실행을 누르기 전에 OpenRouter에서 접수를 확인합니다.

### localhost에서 입력을 전달하는 방식

공개 HTTPS가 없으면 Worker는 참조 이미지와 영상 전체 분석 입력을 data URL로 요청에 포함합니다. 파일당 `GENJUTSU_MAX_INLINE_MEDIA_MB`(기본 20MB) 이하만 보낼 수 있으며 넘으면 요청 전에 실패합니다. 분석은 기본으로 영상에서 추출한 샘플 프레임을 요청에 포함합니다.

OpenRouter는 영상 참조를 **공개 HTTPS URL로만** 받습니다. data URL은 거절하고 파일 업로드 API(`/files`)는 영상을 받지 않습니다. 그래서 `GENJUTSU_PUBLIC_URL`이 `http://localhost:8000`이면 서버 검증이 원본 영상이 연결된 OpenRouter 영상 단계를 막습니다. 이전 버전의 fal/Replicate 업로드 경로는 제거됐습니다.

## 원본 영상으로 모션 전이: 공개 HTTPS

본인 PC에서 모션 전이를 시험하려면 [Cloudflare Tunnel 가이드](cloudflare-staging.ko.md)로 공개 HTTPS 주소를 연결합니다. Cloudflare에 연결한 도메인이 필요합니다. `.env`의 `GENJUTSU_PUBLIC_URL`, `GENJUTSU_DOMAIN`을 공개 주소로, `GENJUTSU_SECURE_COOKIES=true`로 바꾸고 `tunnel` 프로필로 다시 시작합니다. 공개 HTTPS에서는 Worker가 만료되는 서명 URL로 입력을 전달하므로 Cloudflare Access·봇 챌린지가 `/api/assets/*/content`를 막지 않아야 합니다.

1. **모션 전이 · OpenRouter** 템플릿으로 새 프로젝트를 만들고 원본·참조를 업로드합니다. **원본 영상 + 참조 이미지 → 모션 전이(Seedance 2.5) → 결과 내보내기**로 구성됩니다.
2. 모션 노드는 참조 이미지를 **인물·스타일 참조**로, 원본 영상을 참조 영상으로 함께 보내고 원본의 동작·카메라·타이밍을 따르도록 하는 기본 프롬프트를 사용합니다. 다른 모델은 **추천 모델**의 영상 참조 가능 모델(Seedance 2.0·2.0 Fast, MiniMax H3, FLUX.3 Video, Runway Aleph 2.0)에서 고릅니다. Veo 3.1, Kling v3.0 Pro, Wan 3.0, Grok Imagine Video 1.5는 이미지→영상만 지원해 원본 영상을 반영하지 않습니다.
3. OpenRouter 영상 작업은 취소할 수 없습니다. 취소를 요청해도 접수된 영상은 최종 상태까지 조회되고 출력 단계는 실행하지 않습니다.

가짜 OpenRouter와 실제 Temporal로 제출·조회·취소·출력 흐름을 자동 검사했습니다. 실제 OpenRouter로는 텍스트, 이미지와 이미지→영상(Grok) 연결만 확인했습니다. **Seedance 2.5는 2026-10-13 실제 시험에서 실제 인물로 보이는 참조 영상을 거절했습니다**(`PrivacyInformation`, 사실적으로 생성한 인물 포함). 참조 영상은 407,696화소 이상이어야 합니다(854×480 이상). 실제 인물 영상의 모션 전이에 쓸 모델과 Higgsfield Genjutsu 대비 품질은 아직 검증하지 않았습니다. 거절되면 작업 내역의 단계 오류에 공급자 사유가 표시됩니다. 실제 생성 품질과 청구액은 공개 HTTPS 환경에서 키를 등록한 뒤 확인해야 합니다.

## 정지와 재시작

```bash
docker compose stop
docker compose start
```

프로젝트·미디어·작업 기록은 Docker 볼륨에 남습니다. 데이터를 유지하려면 `docker compose down --volumes`를 사용하지 않습니다. 문제가 있으면 `docker compose logs --tail=100 api worker`와 `docker compose ps`를 확인합니다.
