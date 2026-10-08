# 컨펌용 PR 초안

예정 브랜치: `feat/release-deployment-pipeline`

현재 서비스 브랜치가 main에 병합되기 전이라면 해당 브랜치를 PR base로 사용한다. 이 문서는 PR 게시가 아니며, 사용자 컨펌 후 새 브랜치와 PR을 작성한다.

## Title

승인 기반 버전 관리와 digest 고정 릴리스·배포 체계 추가

## As-is

개발용 `open-genjutsu:local` 이미지를 덮어쓰고 앱 버전을 여러 곳에 직접 표기해, 운영에 적용된 버전과 코드를 추적하기 어렵습니다. 릴리스 검증·게시 절차와 호환성 확인을 거치는 롤백 체계가 없습니다.

## To-be

단일 SemVer 원본과 Git 태그·SHA·이미지 digest를 묶어 릴리스를 식별합니다. 검증 CI와 승인 후 수동 게시를 분리하고, 운영자가 고정된 이미지와 manifest로 자체 호스팅 서비스를 배포합니다. 변경 검토·브랜치/PR 생성과 실제 릴리스·배포 승인을 구분합니다.

## Details

- `package.json`에서 API·웹 버전을 읽고 lockfile 일치를 검사하는 버전 도구 및 CHANGELOG 추가
- PR/main 검증 CI와 main에서 수동으로 실행하는 GHCR/GitHub Release 게시 워크플로 추가
- GitHub Actions 참조를 commit SHA로 고정하고 게시 권한을 release job으로 제한
- 앱·PostgreSQL·Temporal·Caddy를 digest로 고정하는 Compose override와 릴리스 manifest 추가
- 배포 도구의 dry-run 기본값, 미커밋 preview 적용 차단, 이미지 label 검증, 동시 배포 잠금 구현
- 기존 진행·확인 대기 작업을 차단하고 쓰기를 중지한 상태에서 백업 후 배포
- API 버전·SHA와 해당 Worker의 Workflow/Activity poller 등록 확인 후 배포 상태 기록
- 명시적인 허용 목록과 동일 DB·Workflow·플랫폼 계약에 한해 이미지 롤백 허용; 실패 시 자동 롤백 대신 pending 상태와 백업 보존
- 사용자 컨펌 전 브랜치·커밋·푸시·PR·태그 게시를 진행하지 않는 절차 문서화

검증: 릴리스·백업 계약 검사 14개, API 검사 18개, 프런트엔드 단위 검사 7개 통과. TypeScript 빌드·Python lint·YAML 문법·Compose override 검증과 별도 Docker 이미지 빌드, 실제 Temporal의 독립 테스트 큐에서 Worker poller 검사 통과.

GitHub 호스팅 CI 실행, Environment 보호 규칙 설정, GHCR 게시와 실제 운영 배포는 아직 수행하지 않았습니다. Environment 이름만으로 승인이 강제되지 않으므로 저장소 설정에서 required reviewers를 구성해야 합니다. 배포 대상은 Linux amd64 단일 호스트이며 플랫폼 업그레이드는 별도의 유지보수 작업으로 처리합니다.
