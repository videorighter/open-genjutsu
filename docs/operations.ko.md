# 자체 호스팅 운영

이 배포는 한 호스트의 PostgreSQL 두 개, Temporal Server, API와 Worker, 공유 미디어 볼륨으로 구성한다. 소규모 팀의 자체 호스팅을 대상으로 한다. 호스트 전체 장애에 대한 자동 failover나 여러 지역에 걸친 HA를 제공하지 않는다. 운영자는 호스트·디스크·백업을 관리하고, 공급자별 비용과 사용 정책을 적용해야 한다.

## 설치와 공개 주소

Docker Engine 및 Compose v2, Python 3이 필요하다. 권장 시작 사양은 4 vCPU, 8GB RAM과 미디어 용량을 포함한 20GB 이상의 여유 디스크다. FFmpeg 영상 길이·해상도·동시성에 맞춰 측정하고 늘린다.

```bash
python3 scripts/configure.py
docker compose up -d --build
docker compose ps
```

`.env`에서 관리자 이메일과 초기 비밀번호를 확인한다. 파일을 Git이나 채팅에 공유하지 않는다. API 키는 로그인 후 웹의 API 키 메뉴에서 등록한다. `.env`를 다시 생성하면 암호화된 키와 Temporal 이력을 읽을 수 없으므로 기존 파일을 유지한다.

로컬 기본 주소는 `http://localhost:8000`이고 공개 포트는 loopback에만 바인딩된다. PostgreSQL과 Temporal 포트는 외부에 공개하지 않는다. 실제 외부 영상 공급자가 입력 미디어를 읽으려면 인터넷에서 접근 가능한 HTTPS 주소가 필요하다.

공개 운영 시 DNS를 호스트에 연결한 뒤 `.env`를 설정한다.

```dotenv
GENJUTSU_DOMAIN=studio.example.com
GENJUTSU_PUBLIC_URL=https://studio.example.com
GENJUTSU_SECURE_COOKIES=true
```

```bash
docker compose --profile tls up -d --build
```

Caddy가 인증서 발급과 HTTPS reverse proxy를 담당한다. 80/443 포트와 인증서 발급에 필요한 DNS·네트워크 접근을 허용해야 한다. 다른 reverse proxy를 쓰면 같은 origin으로 `/api`와 웹을 제공하고 위 공개 주소를 실제 사용자 주소와 일치시킨다. HTTPS 인증서 발급 자체는 이번 로컬 환경에서 검증하지 않았다.

서명된 입력 미디어 URL은 제한 시간 동안 공급자가 로그인 없이 읽을 수 있는 bearer URL이다. 운영자 프록시 로그에서 query string을 제거하고, 해당 URL을 분석 도구나 채팅에 노출하지 않는다. 일반 다운로드는 세션 소유권 검사로 보호된다.

## 계정과 키

공개 회원가입은 제공하지 않는다. 관리자는 웹의 사용자 메뉴에서 계정을 발급한다. 비밀번호는 Argon2 해시, 세션 토큰은 해시, 공급자 키는 Fernet으로 암호화해 저장한다. 브라우저에는 HttpOnly 세션과 CSRF cookie만 전달하며, 저장된 키를 다시 반환하지 않는다. 쿠키는 같은 origin에서 사용한다.

Custom/GPU 키는 승인된 API base URL별로 등록한다. 다른 승인 서버에 같은 키를 자동 전송하지 않는다. Custom/GPU endpoint는 운영자가 `GENJUTSU_CUSTOM_API_URLS` JSON 배열에 먼저 등록해야 한다. 결과 CDN도 `GENJUTSU_DOWNLOAD_HOSTS`로 승인한다. HTTPS, 호스트와 DNS 주소를 검사하고 redirect마다 다시 검사한다. 엄격한 SSRF 방어를 위해 운영 네트워크에서도 사설·메타데이터 주소로의 outbound 접근을 차단한다. DNS 검사만으로 DNS rebinding을 완전히 막는다고 가정하지 않는다.

초기 비밀번호 재설정은 컨테이너의 대화형 명령으로 수행한다. 기존 세션도 폐기한다.

```bash
docker compose exec api python -m genjutsu.maintenance reset-password --email user@example.com
```

진행·확인 대기 작업이 있을 때는 공급자 키 변경을 차단한다. 기존 작업을 조회할 키를 잃지 않기 위한 규칙이다. 공급자에서 먼저 키를 폐기해야 하는 보안 사고는 운영자가 공급자 작업 상태와 예약 한도를 별도로 확인한다.

## 한도와 데이터 정리

기본 업로드는 파일당 128MB, 영상은 30초·4K 이하, 이미지는 16MP 이하이며 실제 내용을 검사한다. 실행당 노드는 20개, 유료 단계 4개, 사용자 동시 작업은 2개다. 사용자 미디어 저장 한도는 2GB다. 제한값은 `.env.example`을 참고한다.

한도는 동시 작업 수와 호출 범위 제한이며 달러 단위 예산 예약·자동 정산 시스템은 아니다. 공급자 대시보드의 지출 제한도 반드시 설정한다. 생성 전 웹에서 유료 단계 수와 비용 발생 동의를 받는다.

작업 내역에서 완료·실패·취소 기록을 삭제하고, 사용하지 않는 프로젝트와 미디어를 웹에서 정리할 수 있다. 진행·확인 대기 작업은 삭제할 수 없다. 프로젝트나 작업에서 참조한 미디어도 먼저 연결·기록을 해제해야 삭제된다. 자동으로 사용자 데이터를 삭제하는 보존 정책은 적용하지 않는다.

```bash
docker compose exec -T api python -m genjutsu.maintenance prune-sessions
docker compose exec -T api python -m genjutsu.maintenance prune-orphans
```

첫 명령은 만료 세션·오래된 로그인 시도, 두 번째는 DB가 참조하지 않는 24시간 이상 된 파일만 정리한다. DB가 소유한 사용자 미디어는 삭제하지 않는다.

## 실행·취소·확인 대기

API는 작업 snapshot과 실행 요청을 한 트랜잭션에 저장한다. dispatcher는 고정 Workflow ID로 Temporal을 시작하고, 시작 후 API가 종료돼도 같은 ID로 확인한다. Worker는 영상 요청 전에 제출 의도를 기록한다. 제출 POST는 자동 재시도하지 않는다. 접수 ID가 있으면 durable timer와 GET으로 같은 작업을 계속 조회한다.

접수 응답을 잃었거나 접수된 작업의 상태 조회가 복구되지 않으면 `NEEDS_REVIEW`로 남긴다. 단순 timeout을 이유로 다른 모델을 호출하지 않는다. 이 상태도 동시 작업 한도에 포함한다. 동일한 `request_key` 재요청은 같은 작업을 반환한다.

취소는 요청 접수와 외부 취소 완료를 구분한다. 공급자 취소를 요청한 뒤 상태를 확인하며, 취소가 불가능하면 이미 접수된 작업의 결말을 기다린다. 취소는 이미 발생한 API 비용의 환불을 의미하지 않는다.

관리자가 실제 공급자 대시보드에서 접수 ID를 확인했다면, 세션과 CSRF 인증으로 다음 API를 사용한다. 기존 실행 종료 후 최소 5분이 지난 확인 대기 작업에만 적용한다.

```text
POST /api/admin/jobs/{job_id}/reconcile
{"node_id":"motion","provider_id":"verified-request-id"}
```

fal/Replicate 작업을 같은 접수 ID로 이어 조회하며 새 POST를 보내지 않는다. OpenRouter 응답 유실처럼 접수 ID로 복구할 수 없는 경우, 공급자 실행과 비용 처리를 확인한 운영자가 다음 API로 종료한다. 확인 없이 사용해서는 안 된다.

```text
POST /api/admin/jobs/{job_id}/close-review
{"confirm_external_resolved":true,"reason":"Verified provider result and billing; no outstanding external execution"}
```

작업에 관리자 ID·시간·사유를 기록하고 한도를 해제한다. 외부 작업을 자동 취소하거나 비용을 취소하는 API가 아니다.

## 백업·복구

활성 작업이 없는 유지보수 시간에 실행한다.

```bash
bash scripts/backup.sh
```

스크립트는 진행·확인 대기 작업을 검사하고 API·Worker·Temporal을 중지한 뒤 애플리케이션 DB, Temporal DB, 미디어와 `.env`를 함께 저장한다. 종료 시 서비스를 다시 시작한다. 백업 폴더 권한은 비공개로 생성한다. 백업에는 키가 있으므로 암호화해 별도 호스트로 복사한다. DB만 백업하면 영상이나 이력을 복원할 수 없다.

복구는 새 호스트에서 같은 코드·이미지 버전으로 수행한다. 다음은 빈 목적 DB/볼륨을 준비한 뒤의 절차다. 원래 데이터가 있는 볼륨을 덮어쓰는 복구는 하지 않는다.

1. 백업 SHA256을 확인하고 `environment.env`를 `.env`로 복원한다. 기존 암호화 키를 유지한다.
2. `docker compose up -d db temporal-db`로 빈 DB를 시작한다.
3. `application.dump`를 `pg_restore -U genjutsu -d genjutsu --no-owner`로 복원한다.
4. `temporal.sql`은 역할이 이미 존재하는 경우를 검토한 뒤 `psql -U temporal -d postgres`로 복원한다. 이 dump에는 Temporal DB 두 개와 역할 정보가 들어 있다.
5. 미디어를 `docker compose run --rm --no-deps api tar -C /data -xf -`로 복원한다. 파일 소유자는 앱 UID 10001이어야 한다.
6. Temporal, API, Worker를 시작하고 readyz·작업 기록·실제 결과 다운로드를 확인한다.

매번 빈 격리 환경에서 복구를 연습한다. 이번 검증의 컨테이너 재시작 시험은 백업에서 새 호스트로 복원하는 DR 시험을 대체하지 않는다.

## 업데이트와 관측

```bash
docker compose logs --tail=100 api worker
docker compose ps
curl -fsS http://localhost:8000/api/readyz
```

`healthz`는 API 프로세스, `readyz`는 DB·Temporal 연결을 검사한다. readyz만으로 Worker의 처리 능력까지 확인하지 않는다. Worker 로그, 대기 작업과 오래된 확인 대기 작업, 디스크·DB 용량도 모니터링한다. 일반 로그에는 작업 ID와 오류 종류만 남기며 프롬프트·키·미디어 URL을 넣지 않는다. Temporal payload도 같은 서버 키로 암호화한다.

API 시작 시 Alembic migration을 적용하며 PostgreSQL advisory lock으로 중복 실행을 막는다. 진행 중인 Workflow가 있을 때는 호환되지 않는 Workflow 코드를 배포하지 않는다. V1 Worker를 유지하거나 새 Workflow 이름과 큐를 만들어 단계적으로 전환한다. 릴리스 전 실제 이력 Replayer 시험이 필요하다. SDK·서버·DB 버전은 검증 후 올리고, 자동 rollback이 DB schema를 되돌린다고 가정하지 않는다.

이 구성은 체크포인트가 있는 GPU 추론, OAuth/SSO, 결제·정산, webhook inbox, 자동 비용 fallback, S3 분산 저장을 제공하지 않는다. GPU/Custom API 서버는 별도 운영하고 [공급자 계약](provider-contract.ko.md)에 맞춰 연결한다.
