# 로컬에서 테스트하기

Docker가 설치된 자신의 컴퓨터에서 웹 UI, 프로젝트 저장, Temporal 실행과 실제 모델 API를 테스트합니다. OpenRouter는 분석·프롬프트를, fal/Replicate는 영상 생성을 담당합니다. 도메인·Cloudflare·VPS·릴리스 게시 설정은 필요하지 않습니다.

## 시작

Docker Engine/Docker Desktop, Compose 2.24.4 이상, Git과 Python 3을 준비합니다. 로컬 테스트 변경은 `feat/local-testing` 브랜치에 있습니다.

```bash
git clone --branch feat/local-testing https://github.com/videorighter/open-genjutsu.git
cd open-genjutsu
```

기존 체크아웃에서는 작업 내용을 보존한 뒤 `git fetch origin feat/local-testing`과 `git switch feat/local-testing`으로 이동합니다. 저장소 디렉터리에서 아래 명령을 실행합니다. `.env`가 없다면 처음 한 번만 생성합니다. Windows에서는 설치 형태에 따라 `python3` 대신 `python` 또는 `py -3`을 사용합니다.

```bash
python3 scripts/configure.py
docker compose up -d --build --wait --wait-timeout 180
docker compose ps
```

이미 `.env`가 있으면 첫 명령은 건너뛰고 기존 키와 비밀번호를 유지합니다. 로컬 설정은 다음과 같습니다.

```dotenv
HTTP_PORT=8000
GENJUTSU_PUBLIC_URL=http://localhost:8000
GENJUTSU_SECURE_COOKIES=false
GENJUTSU_MEDIA_DELIVERY=upload
```

이 주소는 **Docker를 실행한 본인의 컴퓨터**에서 엽니다. 원격 개발 환경의 localhost는 자신의 PC에 자동 연결되지 않습니다. `.env`에서 관리자 이메일·비밀번호를 확인해 로그인합니다. API 포트는 127.0.0.1에만 연결하며 DB와 Temporal 포트는 외부에 공개하지 않습니다. `tls`·`tunnel` 프로필은 켜지 않습니다.

## 비용 없이 영상 처리 확인

1. 상단 **새 프로젝트 템플릿**에서 **로컬 영상 테스트 · 무료**를 선택하고 **새 프로젝트**를 누릅니다.
2. **원본 영상 → 결과 내보내기**의 두 노드가 나타납니다. 원본 노드에서 30초 이하 영상 파일을 업로드합니다. 기본 파일 상한은 128 MB입니다.
3. 미리보기를 확인하고 서버 저장 후 새로고침해도 파일과 설정이 남는지 확인합니다.
4. **실행 계획 → 생성 시작**을 누릅니다. 유료 모델 단계가 없어 API 키와 비용 동의가 필요하지 않습니다.
5. **작업 내역**에서 완료된 MP4를 내려받아 확인합니다. 원본에 오디오가 있으면 출력에도 포함됩니다.

이 템플릿은 Temporal과 FFmpeg의 업로드·처리·저장·다운로드 흐름을 확인합니다. 캐릭터 교체나 AI 모션 전이를 수행하는 템플릿은 별도의 모델을 연결합니다.

## 실제 모델 테스트: 총 $10 이내

1. 무료 영상 처리부터 성공하는지 확인합니다. 첫 AI 입력은 실제 움직임이 있는 **3~5초 영상 1개와 참조 이미지 1개**로 준비합니다. 같은 입력을 모델마다 비교합니다.
2. 공급자 계정에서 자동 충전을 끄고 지출 제한을 설정합니다. 승인된 총액은 **$10**이며, 앱의 비용 동의는 달러 한도를 강제하지 않습니다. 공급자별 최대 청구액을 확정할 수 없는 요청은 보내지 않습니다.
3. **API 키**에서 fal 키를 등록합니다. 분석·프롬프트를 추가할 때만 OpenRouter 키도 등록합니다. OpenRouter 키로 fal 영상을 생성할 수는 없습니다. 키를 채팅·프로젝트 JSON·Git에 넣지 않습니다.
4. **Wan 모션 전이** 템플릿으로 새 프로젝트를 만들고 원본·참조를 업로드합니다. 모션 노드의 모델과 지원 해상도를 확인합니다. 기본 Wan은 자유 프롬프트를 받지 않으므로 첫 비교에 유료 언어 모델은 필요하지 않습니다.
5. **실행 계획**의 오류와 경고를 확인합니다. 현재 단가·길이·해상도·최소 청구 단위·실패 과금을 공급자에서 확인한 뒤 비용 발생에 동의하고 한 번만 실행합니다.
6. 완료 MP4와 공급자 대시보드의 **실제 청구액**을 확인합니다. 남은 예산 안에서 Kling, VACE 순으로 비교합니다. VACE는 `pose`부터 시작하고 inpainting은 모델 요구에 맞는 마스크가 준비된 경우에만 사용합니다. 분석·프롬프트 노드는 필요할 때 OpenRouter로 추가합니다.

최대 배정액은 OpenRouter $0.50, Wan $2.50, Kling $3, VACE $3, 예비 $1입니다. 이는 가격 견적이 아닙니다. 요청 상한이 배정액을 넘으면 입력을 줄이거나 해당 모델 비교를 보류합니다. 상세 기록·중단 기준은 [실제 모델 평가](model-evaluation.ko.md)를 따릅니다. 접수 여부가 불명확한 작업은 **공급자 확인 대기**로 남으며 새 실행을 누르기 전에 공급자에서 접수를 확인합니다.

### localhost에서 입력을 전달하는 방식

`GENJUTSU_MEDIA_DELIVERY=upload`이면 Worker가 fal의 저장소 업로드 API 또는 Replicate의 `/v1/files` API로 연결된 입력을 전송하고 공급자 파일 URL로 생성 요청을 보냅니다. 공급자가 이 PC의 localhost에 접근할 필요가 없습니다. 파일은 해당 공급자 저장소에도 보관되며 공급자 보관 정책이 적용됩니다. fal에는 만료 선호 설정을 전달합니다. 업로드 실패는 생성 요청 전에 종료합니다.

Replicate를 사용하려면 해당 키와 모델 ID 외에 공식 schema에 맞는 **공급자 입력 JSON**을 지정합니다. `$video`, `$image`, `$images`는 업로드된 파일 URL로 치환합니다. OpenRouter 분석은 영상에서 추출한 샘플 프레임을 요청에 포함합니다.

기존 `.env`에 설정이 없으면 호환성을 위해 `signed` 방식이 유지됩니다. 로컬 테스트에서는 `GENJUTSU_MEDIA_DELIVERY=upload`를 명시하고 Compose를 다시 실행합니다. `signed` 방식과 Custom/GPU 영상 서버는 공급자가 읽을 수 있는 공개 HTTPS 입력 주소가 필요합니다. 이 저장소는 로컬 GPU 추론 서버를 포함하지 않습니다.

공식 파일 API 계약, 가짜 공급자를 통한 업로드·실패 처리와 실제 Temporal 실행은 자동 검사로 확인했습니다. **실제 공급자 업로드 성공, 모델 생성 품질과 청구액은 본인 PC에서 키를 등록한 뒤 확인해야 합니다.** 이 준비 과정에서 유료 호출은 하지 않았습니다.

## 정지와 재시작

```bash
docker compose stop
docker compose start
```

프로젝트·미디어·작업 기록은 Docker 볼륨에 남습니다. 데이터를 유지하려면 `docker compose down --volumes`를 사용하지 않습니다. 문제가 있으면 `docker compose logs --tail=100 api worker`와 `docker compose ps`를 확인합니다.
