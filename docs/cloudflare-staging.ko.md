# Cloudflare로 스테이징 열기

Cloudflare Tunnel을 사용하면 공유기 포트 개방이나 고정 IP 없이 HTTPS로 서비스를 연결할 수 있습니다. Cloudflare는 접속 경로를 제공하고 **Docker 서비스는 본인의 컴퓨터 또는 VPS에서 실행**합니다. 상시 켜둘 Linux 서버가 있으면 그 서버를 사용하세요. 없으면 Ubuntu VPS를 준비합니다. 현재 릴리스 이미지의 지원 아키텍처는 `linux/amd64`입니다.

본인 PC에서 테스트할 때는 Tunnel과 도메인이 필요하지 않습니다. 기본 `GENJUTSU_MEDIA_DELIVERY=upload`는 fal/Replicate에 입력을 직접 업로드합니다. [로컬 테스트 가이드](local-testing.ko.md)를 먼저 따르세요. 아래 공개 입력 접근 설정은 `signed` 방식과 Custom/GPU 영상 경로에 적용합니다.

## 1. 도메인과 Docker 호스트 준비

1. 도메인을 구매하거나 보유한 도메인을 Cloudflare에 추가합니다. 등록기관에서 Cloudflare가 안내한 네임서버로 변경하고 활성화될 때까지 기다립니다.
2. Docker Engine과 Compose 플러그인 2.24.4 이상을 설치한 Linux 호스트를 준비합니다. 영상 저장 공간과 백업 공간을 확보합니다. DB·Temporal 포트는 외부에 공개하지 않습니다.
3. 서버에서 이 저장소를 가져옵니다. 테스트에 사용할 버전은 [릴리스 절차](release-process.ko.md)의 승인된 RC로 고정합니다. 소스 빌드 시험은 아래 명령을 사용하고, RC 배포는 마지막 절의 digest 배포를 사용합니다.

```bash
git clone https://github.com/videorighter/open-genjutsu.git
cd open-genjutsu
python3 scripts/configure.py
```

`.env`는 서버에서만 편집합니다. 이미 있다면 `configure.py`로 재생성하지 마세요. `GENJUTSU_SECRET_KEY`가 바뀌면 기존 암호화된 API 키와 Temporal 이력을 읽을 수 없습니다.

## 2. Tunnel 만들기

Cloudflare 대시보드에서 **Zero Trust → Networks → Connectors → Cloudflare Tunnels**를 엽니다. 메뉴 이름은 계정에 따라 다를 수 있습니다.

1. Tunnel 생성 → `cloudflared` → 이름 `open-genjutsu-staging`.
2. Docker 설치 안내의 `--token` 뒤 문자열을 개인 서버의 `.env`에 `CLOUDFLARE_TUNNEL_TOKEN=…`으로 저장합니다. 채팅·Git·스크린샷에 넣지 않습니다. 안내 명령으로 별도 컨테이너를 실행할 필요는 없습니다. Compose가 실행합니다.
3. Published application route/Public hostname을 추가합니다.
   - Subdomain: `staging`
   - Domain: 본인의 도메인
   - Service type: `HTTP`
   - URL: `api:8000`

`api:8000`은 같은 Compose 네트워크 안의 서비스 주소입니다. Cloudflare 대시보드에 `localhost:8000`을 입력하면 Tunnel 컨테이너 자기 자신을 가리켜 연결되지 않습니다.

## 3. 서비스 설정과 시작

`.env`에서 다음 공개 설정을 변경하고 관리자 이메일을 설정합니다. Tunnel 토큰과 관리자 비밀번호는 아래 예시에 쓰지 않았습니다.

```dotenv
GENJUTSU_PUBLIC_URL=https://staging.example.com
GENJUTSU_DOMAIN=staging.example.com
GENJUTSU_SECURE_COOKIES=true
GENJUTSU_MAX_UPLOAD_MB=90
```

Cloudflare Free/Pro의 기본 요청 업로드 상한은 100 MB이므로 파일은 90 MB 이하로 제한합니다. 더 큰 원본은 짧게 잘라 테스트합니다. 큰 파일이 필요하면 Cloudflare 요금제 및 직접 TLS 접속 구성을 검토합니다.

```bash
docker compose -f compose.yaml -f compose.tunnel.yaml --profile tunnel up -d --build
docker compose -f compose.yaml -f compose.tunnel.yaml --profile tunnel ps
docker compose -f compose.yaml -f compose.tunnel.yaml --profile tunnel logs --tail=50 tunnel
```

Cloudflare Tunnel 상태가 Healthy가 되면 자신의 `https://staging.example.com`에서 로그인합니다. HTTPS가 끝나는 곳은 Cloudflare이고, Tunnel과 API 사이의 HTTP는 Docker 내부 네트워크를 사용합니다. TLS Caddy 프로필은 동시에 켜지 않습니다.

## 4. 공개 경로와 모델 키 확인

- 로그인 후 원본 영상·참조 이미지를 업로드하고 미리보기와 새로고침 후 저장 상태를 확인합니다.
- `API 키`에서 OpenRouter 및 사용할 영상 공급자(fal/Replicate)의 키를 저장합니다. OpenRouter 키만으로 fal 영상 모델을 실행할 수는 없습니다.
- `signed` 또는 Custom/GPU 영상 경로에서는 공급자가 서명된 미디어 URL에 접근해야 합니다. 전체 호스트에 Cloudflare Access 로그인이나 봇 챌린지를 적용하면 이 접근이 막힙니다. 접근 정책을 추가할 때 `/api/assets/*/content`의 서명 요청 경로와 필요한 `/api/readyz`, `/api/version`을 별도로 검토하세요. 서비스의 계정 로그인·소유권·만료 서명 검증은 계속 적용됩니다.
- 사용자 계정은 관리자의 `사용자` 메뉴에서 발급합니다. 관리자의 키는 다른 사용자에게 공유되지 않습니다. 실제 API 평가에 쓸 계정에 키를 저장합니다.
- 유료 시험 총 승인액은 **$10**입니다. 공급자별 잔액·키 제한과 현재 가격을 먼저 확인하고, 합계 $10 이하의 고정된 시험만 실행합니다. 예상 비용만으로 실제 청구 상한이 보장되지는 않습니다. 자동 충전은 끄고 초과 위험이 있는 시험은 실행하지 않습니다.

## 5. 승인된 RC 이미지 배포

Release에서 `release.json`과 `SHA256SUMS`를 받아 체크섬을 검증한 다음, 서버의 같은 버전 코드에서 실행합니다.

```bash
python3 scripts/deploy.py release.json --tunnel
# 위 계획과 릴리스 메타데이터를 확인한 뒤 실제 적용
python3 scripts/deploy.py release.json --tunnel --apply
```

배포 스크립트는 RC 이미지 digest와 앱 버전·커밋, DB·Temporal 계약, API readiness 및 Worker poller를 확인합니다. 호스트의 첫 실행과 이후 업데이트 절차는 [릴리스 문서](release-process.ko.md)를 따릅니다. Tunnel 프로세스가 살아 있는 것만으로 외부 HTTPS 연결이 확인되지는 않으므로 브라우저 로그인과 미디어 접근도 확인합니다.

## 준비 후 알려줄 정보

**공개 스테이징 URL**과 배포 호스트를 알려주세요. 직접 서버 배포를 진행하려면 환경 보안 설정에 SSH 접속을 등록하고 별칭/접속 주소만 공유합니다. 본인이 위 명령으로 배포하면 URL만 공유해도 외부 검증을 진행할 수 있습니다. 비밀번호·Tunnel 토큰·모델 API 키는 채팅에 보내지 않습니다.

`502`는 `api:8000` 경로와 API health, `413`은 업로드 크기, 로그인 반복은 HTTPS public URL과 secure cookie 설정, 공급자 미디어 다운로드 실패는 Access/WAF 정책과 서명 만료부터 확인합니다.
