# 웹 워크플로 스튜디오

React + TypeScript + Vite + React Flow로 구현했다. `src/workflow.ts`는 노드/모델 목록, 가져오기 검증, DAG 연결 검사, 위상 정렬과 실행 계획 생성을 담당한다. `src/App.tsx`는 캔버스, 노드 라이브러리, 설정 패널, 자동 저장과 JSON 교환을 담당한다.

## 저장 형식

워크플로 JSON은 `version: 1`, `title`, `nodes`, `edges`로 구성된다. 각 노드는 ID와 캔버스 위치, `kind`, `label`, `provider`, `model`, `prompt`, `temperature`, `seed`, `resolution`, 선택적인 사용자 지정 `endpoint` 및 미디어 파일명 메타데이터를 가진다. API 키나 미디어 bytes는 포함하지 않는다.

가져오기는 버전, 크기(2MB), 노드/연결 개수, 유일한 ID, 위치와 파라미터 형식, 연결 대상, 중복 및 순환을 검사한다. 유효하지 않은 파일은 현재 그래프를 바꾸지 않는다. 모델 ID는 목록 밖의 값도 보존한다.

설정은 `open-genjutsu.workflow.v1` 키로 브라우저 localStorage에 자동 저장된다. 일반 편집은 550ms 지연 후 저장하며, 새로고침·페이지 이탈·탭 숨김 시 대기 중인 변경을 즉시 저장한다. 저장소를 사용할 수 없거나 용량이 부족하면 헤더와 모바일에서도 보이는 알림에 저장 실패를 표시하고 JSON 내보내기를 사용할 수 있다. 저장은 서버나 여러 기기 사이에 동기화되지 않는다.

## 실행 계획

실행 계획은 각 노드의 `node_id`, `task`, `provider`, `model`, `prompt`, 선택적인 `endpoint`, `parameters`, `input_nodes`를 위상 순서로 내보낸다. 이는 미래 실행기에 전달할 초안이지 실제 Temporal 실행이나 공급자 요청이 아니다.

현재 파라미터 값은 공통 편집 설정이다. 실행기에서 모델마다 지원되는 파라미터를 매핑하고, 지원하지 않는 값은 사용자에게 알려야 한다. 모델 ID를 자유롭게 바꿀 수 있다는 사실이 모든 노드 태스크의 호환성을 보장하지는 않는다. UI는 Wan-Animate의 프롬프트 미지원과 OpenRouter의 영상 출력 미지원 등을 표시한다.

Temporal 연결 시 FastAPI가 다음을 담당해야 한다.

1. 워크플로를 서버에서 다시 검증하고 미디어 asset ID를 확보한다.
2. 모델 카탈로그 버전, 능력, 허용 API endpoint와 비용 상한을 고정한다.
3. 클라이언트 요청 키와 DB outbox로 GenerationWorkflow를 시작한다.
4. 각 노드를 Activity 또는 ModelExecutionWorkflow에 매핑한다.
5. Workflow Query/Signal/Update를 UI 상태 조회·취소에 연결한다.

현재 클라이언트 코드에서 외부 API 주소를 호출하거나 키를 저장하지 않는다. Custom API 주소는 계획에 보존되는 설정값이며, 실제 서버 연결 전에 내부 주소 접근 제한과 공급자 인증 검증이 필요하다.

## 미디어와 샘플

기본 노드 카드의 풍경/인물 그림은 UI용 CSS 일러스트레이션이며 입력 미디어가 아니다. 실제 파일은 입력 노드를 선택해 연결할 수 있다. 미리보기 URL은 현재 세션에서만 유효하고, 새로고침 뒤 파일명 메타데이터만 남는다. 실제 실행 전에는 서버 업로드와 자산 등록이 필요하다.

모달이 열리면 배경을 `inert`로 처리하고 캔버스 삭제 단축키를 비활성화한다. Tab 포커스는 대화상자 안에 유지하며 Escape로 닫은 후 실행 버튼으로 복원한다.
