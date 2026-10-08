# 버전 관리와 배포 절차

이 체계는 소규모 팀의 Linux amd64 단일 호스트 Docker Compose 배포를 대상으로 한다. 개발 빌드와 릴리스 빌드를 분리하고, 버전·코드·이미지·DB·Workflow 계약을 함께 기록한다. 자동 운영 배포는 하지 않는다.

## 변경 승인과 브랜치

1. 변경을 로컬에서 작성·검증하고 사용자에게 변경 내역, 영향과 PR 초안을 제시한다.
2. 사용자가 해당 변경을 컨펌한 뒤에만 별도 브랜치를 생성하고 커밋·푸시·PR 게시를 진행한다.
3. PR 검증 후 병합한다. PR 승인과 릴리스 게시·운영 배포 승인은 별개다.

이번 변경의 예정 브랜치는 `feat/release-deployment-pipeline`이다. 현재 서비스 구현 브랜치가 main에 병합되기 전이라면 해당 서비스 브랜치를 base로 하는 별도 PR을 작성한다. 서비스 구현이 병합되면 main을 base로 정리해 이 변경만 리뷰할 수 있도록 한다.

브랜치는 `feat/<기능>`, `fix/<수정>`, `chore/<운영>`을 사용한다. 버전 준비 PR은 `release/v<버전>`을 사용하며, 승인 없이 bot이 버전 PR·태그를 만들지 않는다.

## 버전 규칙

`package.json`의 `version`이 유일한 앱 버전 원본이다. lockfile의 루트 버전은 일치해야 하며, API의 `/api/version`과 화면은 이 값을 읽는다. Docker에는 같은 버전과 전체 Git SHA를 OCI label로 기록한다.

- `MAJOR.MINOR.PATCH`: 안정 릴리스. 예: `0.3.0`.
- `MAJOR.MINOR.PATCH-rc.N`: 사전 검증 후보. 예: `0.3.0-rc.1`.
- PATCH: 호환되는 수정. MINOR: 호환되는 기능 추가. MAJOR: API·데이터·실행 계약의 비호환 변경.
- 0.x 단계의 비호환 변경도 MINOR를 올리고 변경·복구 계획을 명시한다.
- 공개한 버전과 태그는 재사용·덮어쓰기하지 않는다. 운영에 `latest`를 사용하지 않는다.

현재 버전은 0.2.0이며 이 변경을 작성하는 것만으로 다음 버전을 릴리스하지 않는다. 다음 버전 준비 시 다음 명령으로 manifest와 lockfile을 함께 바꾸고, CHANGELOG의 Unreleased 항목을 해당 버전 섹션으로 이동한다.

```bash
python3 scripts/release.py set-version 0.3.0-rc.1
# CHANGELOG.md에 '## 0.3.0-rc.1'과 검토 가능한 릴리스 노트 추가
python3 scripts/release.py check
```

RC에서 안정판으로 올릴 때도 새 PR에서 버전·릴리스 노트를 갱신한다. `set-version`은 Git 브랜치·태그·PR을 만들지 않는다.

## CI와 수동 릴리스

PR과 main에서는 `.github/workflows/ci.yml`이 버전·릴리스 계약, Python lint/API 검사, 프런트엔드 빌드·단위 검사·브라우저 검사와 실제 Compose/Temporal 장애 복구 검사를 수행한다. Compose 재시작 검사와 서비스 브라우저 검사는 순차 실행한다. CI는 폐기 가능한 볼륨만 사용한다.

main에 병합한 뒤 운영자가 GitHub Actions의 **Publish approved version**을 수동 실행하고 정확한 버전을 입력한다. 릴리스 요청은 main에서만 허용하며 검증 CI가 다시 통과해야 게시 단계로 넘어간다.

GitHub 저장소에서 사전에 다음을 설정한다.

- main 보호 및 필수 checks/compose 검증, 강제 push 제한.
- `release` Environment에 required reviewers와 필요한 승인 정책 설정.
- GHCR package 사용 권한과 visibility 확인. 다른 호스트에서 익명 pull을 하려면 package를 공개해야 한다. 비공개 package는 호스트에서 읽기 전용 registry 인증을 별도로 설정한다.

`environment: release`라는 이름만으로 사람의 승인이 강제되지는 않는다. 저장소의 Environment 보호 규칙이 필요하며 GitHub 요금제·저장소 visibility에 따라 지원 범위를 확인한다. 보호 규칙 설정은 이번 로컬 작업에서 적용하지 않는다.

게시 워크플로는 체크한 commit에서 Linux amd64 이미지를 빌드하고 다음을 생성한다.

| 산출물 | 예 |
| --- | --- |
| Git 태그 | `v0.3.0-rc.1` |
| GHCR 버전 이미지 | `ghcr.io/videorighter/open-genjutsu:v0.3.0-rc.1` |
| 코드 식별 태그 | `ghcr.io/videorighter/open-genjutsu:sha-<전체 Git SHA>` |
| 배포용 이미지 참조 | `ghcr.io/videorighter/open-genjutsu@sha256:<digest>` |
| GitHub Release 파일 | `release.json`, `SHA256SUMS` |

배포는 버전 태그 대신 manifest의 digest를 사용한다. manifest에는 앱 버전·SHA, 고정 플랫폼 이미지, migration head·선행 revision, Workflow 이름과 허용된 이미지 롤백 버전이 들어 있다. SHA256 파일은 무결성 검사이며 게시자 서명을 대신하지 않는다. 공식 저장소의 Release에서 받아 사용한다.

릴리스 manifest는 변경 사항이 없는 checkout에서만 생성한다. 로컬 미커밋 상태의 검토에는 `scripts/release.py manifest --image <digest 참조> --allow-dirty`를 사용할 수 있지만, 이 결과는 development preview로 표시되어 실제 배포가 차단된다.

게시 직전에 태그로 버전을 예약한다. 태그 생성 이후 이미지 push나 Release 게시가 실패한 경우에도 버전을 자동 재사용하거나 태그를 삭제하지 않는다. 상황을 확인하고 새 PATCH/RC 번호로 다시 릴리스한다. 아직 릴리스된 것이 아닌 예약 태그만 남을 수 있다.

## 배포와 확인

호스트에는 Docker Compose 2.24.4 이상, Python 3, Bash가 필요하다. 릴리스 manifest를 공식 Release에서 내려받아 checksum을 확인한다. `.env`는 기존 파일을 유지하며 생성·재설정하지 않는다.

```bash
# 내려받은 두 파일을 같은 디렉터리에 보관하고 해시 비교
sha256sum release.json
cat SHA256SUMS

# 먼저 계획을 확인한다. Docker나 Git 상태를 바꾸지 않는다.
python3 scripts/deploy.py release.json

# 운영자의 배포 승인 후 적용한다. HTTPS 운영이면 --tls 추가
python3 scripts/deploy.py release.json --apply --tls
```

HTTP_PORT를 변경했다면 `--url http://127.0.0.1:<포트>`로 로컬 검사 주소를 지정한다. HTTPS cookie를 사용하는 공개 서비스도 배포 확인은 공개 proxy를 통과하지 않는 loopback API를 사용한다.

적용 시 이미지 label과 manifest를 대조하고 기존 DB revision이 목표 migration의 선행 단계인지 확인한다. PostgreSQL·Temporal·Caddy 이미지를 바꾸는 앱 배포는 차단한다. 플랫폼 버전 변경은 별도의 백업·복구·호환성 검토와 유지보수 절차를 따른다.

기존 서비스의 진행·확인 대기 작업이 없을 때만 배포하며, 두 번의 작업 확인과 쓰기 중지로 백업 중 새 제출을 방지한다. DB 두 개·미디어·암호화 키를 함께 백업한 뒤 서비스 쓰기를 중지한 상태를 유지한다. 고정 이미지로 서비스를 시작하고 API readyz, 버전·SHA와 해당 Worker의 Workflow/Activity poller 등록을 확인한다. 초기 설치에도 같은 이미지 고정과 상태 검사를 수행한다.

성공한 배포는 `.release/deployed.json`, 직전 배포는 `.release/previous.json`에 기록한다. 적용 도중 실패하면 `.release/pending.json`과 백업을 남기고 자동 롤백하지 않는다. 이는 중간 상태를 완료로 기록하지 않기 위한 규칙이다. Worker poller 검사는 실제 생성 품질 검사가 아니며 배포 후 유료 호출이 없는 대표 작업도 확인한다.

## 운영 명령과 백업

릴리스 배포 후 관리 명령에도 같은 Compose override와 이미지 설정을 사용한다. 아래 예시는 저장소 루트에서 실행한다.

```bash
set -a
. .release/images.env
set +a
export COMPOSE_FILE=compose.yaml:compose.release.yaml
docker compose ps
docker compose logs --tail=100 api worker
bash scripts/backup.sh
```

운영 이미지로 배포한 호스트에서 기본 `docker compose up --build`를 실행하면 로컬 개발 이미지로 바뀔 수 있으므로 위 구성을 유지한다. 새 릴리스 배포는 도구가 환경을 직접 구성하므로 위 export가 필요하지 않다.

## 롤백과 호환성

이미지 롤백은 현재 manifest의 `rollback_compatible_versions`에 명시적으로 선언한 버전에만 허용한다. 게시 입력의 `rollback_compatible`에는 이전 릴리스로 되돌리는 검증을 마친 버전만 넣는다. 기본값은 비어 있으며 자동 추정하지 않는다.

```bash
python3 scripts/deploy.py .release/previous.json --rollback
# 실제 적용은 운영자의 승인 후
python3 scripts/deploy.py .release/previous.json --rollback --apply --tls
```

현재 DB revision, migration 계약, Workflow 이름, 플랫폼 이미지가 같아야 이미지 롤백을 허용한다. 같다는 사실만으로 코드 호환성이 입증되지는 않으므로 이전 API/Worker 실행과 대표 작업을 반드시 검증한 뒤 허용 목록에 추가한다. 앱 변경에는 기본적으로 additive migration을 사용한다. 데이터 삭제·컬럼 제거·계약 변경은 여러 릴리스에 나누고 복구 계획을 검토한다.

DB schema 또는 Workflow 계약이 바뀌면 이전 이미지만 덮어쓰지 않는다. 조정된 백업에서 전체 복원하거나 forward fix를 릴리스한다. Workflow 이름은 SemVer와 별개이며, 실행 이력과 코드를 호환시키거나 V1/V2 Worker와 task queue를 병행해야 한다. CI의 실제 이력 replay 검사를 유지한다.

실패한 배포에서 API 자체가 실행되지 않는 경우에는 도구의 일반 롤백 검사를 우회하지 않는다. 백업 복원 또는 운영자가 검토한 수동 복구 절차를 사용하고 pending manifest를 실제 실행 상태와 맞춘다. 상세 복원은 [운영 가이드](operations.ko.md)를 따른다.

## 검증 범위

이 체계의 로컬 검사 결과는 PR 초안에 기록한다. GitHub 호스팅 CI, Environment 승인, GHCR push 및 운영 적용은 실제 게시·승인 후 별도 확인한다. 로컬 dry-run 통과를 운영 배포 성공으로 표현하지 않는다. 컨펌 전에는 브랜치·커밋·PR·태그·Release를 생성하지 않는다.
