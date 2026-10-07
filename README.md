# Open Genjutsu

[한국어](README.md) · [English](README.en.md) · [简体中文](README.zh-CN.md)

여러 영상 모델을 조합하는 노드 기반 워크플로 스튜디오입니다. 각 노드의 API 공급자, 모델 ID, 프롬프트와 생성 설정을 독립적으로 바꿀 수 있습니다.

## 실행

Node.js 22.12 이상이 필요합니다. 현재 환경에서는 Node.js 24로 검증했습니다.

```bash
npm ci
npm run dev
```

## 웹 UI

- 노드 추가, 드래그 배치, 포트 연결, 복제·삭제·되돌리기.
- OpenRouter, fal, Replicate, GPU Worker, Custom API, Local 공급자 선택.
- 추천 모델 선택 또는 사용자 지정 모델 ID와 API 주소 입력.
- 노드별 프롬프트, temperature, seed, 해상도 편집.
- 브라우저 자동 저장 및 워크플로 JSON 가져오기·내보내기.
- 순환·중복 연결 차단, 잘못된 JSON 검증, 실행 순서와 모델 호환성 주의 사항 확인.
- 데스크톱·모바일 편집과 현재 세션의 미디어 미리보기.

현재 구현은 **워크플로 편집기와 실행 계획 미리보기**입니다. Temporal, 인증·키 관리, 영상 생성 API는 아직 연결되지 않았습니다. 실행 계획 버튼은 실제 생성이나 과금 없이 JSON 계획을 검증·내보냅니다. API 키를 UI 또는 워크플로 JSON에 넣지 마세요.

미디어 파일은 브라우저 세션에서만 미리보기하며 서버로 업로드하지 않습니다. 새로고침 후 파일을 다시 연결해야 합니다. 브라우저 저장소는 사용자·기기별이며, 다른 환경으로 이동하려면 JSON을 내보내세요.

## 검증

```bash
npm test
npm run build
npm run test:e2e
```

`test:e2e`는 프로덕션 빌드를 만든 뒤 Playwright로 데스크톱·모바일 Chromium을 직접 조작합니다. 이 환경의 `/usr/bin/chromium`을 자동 사용하며, 다른 실행 파일은 `PLAYWRIGHT_CHROMIUM_EXECUTABLE`로 지정할 수 있습니다. 시스템 Chromium이 없는 환경에서는 먼저 `npx playwright install chromium`을 실행하세요. 브라우저 실행에는 해당 OS의 브라우저 의존 패키지도 필요합니다.

`npm run test:e2e:report`로 HTML 결과를 열 수 있습니다. 실패한 테스트의 스크린샷·trace는 `test-results/`에 저장합니다. 검증은 영상 생성 API를 호출하지 않습니다.

- [직접 브라우저 검증 결과](docs/browser-validation.ko.md)

## 설계

- [모델 조사와 구현 계획](docs/genjutsu-research-and-plan.ko.md)
- [Temporal 기반 실행 아키텍처](docs/temporal-architecture.ko.md)
- [웹 편집기 데이터와 실행기 연결](docs/web-studio.ko.md)
