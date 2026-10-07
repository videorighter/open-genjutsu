# 웹 스튜디오와 서버 데이터

기본 모드는 로그인하는 서비스이며 `src/ServiceApp.tsx`가 세션·프로젝트·키·미디어·작업 내역을 관리한다. `src/App.tsx`는 노드 편집과 실행 확인을 담당한다. `npm run dev:editor`는 서버 없이 편집하는 별도 모드다.

워크플로 JSON은 `version: 1`, `title`, `nodes`, `edges`로 구성된다. 노드는 ID, 위치, kind·label·provider·model·prompt·temperature·seed·resolution과 선택적인 endpoint·assetId·미디어 메타데이터·providerInput을 가진다. API 키와 미디어 bytes는 포함하지 않는다. JSON의 assetId는 서버 자산 참조이므로 다른 서버에 가져오면 파일을 다시 업로드해야 한다.

서비스는 계정별 프로젝트와 revision을 PostgreSQL에 저장한다. 편집을 550ms 지연 후 직렬로 저장하며 서버 확인 후 저장 완료를 표시한다. 아직 확인되지 않은 수정이 있으면 페이지 이탈을 경고한다. 프로젝트 변경·로그아웃·생성 접수 전에도 저장을 기다린다. 다른 탭의 변경으로 revision이 다르면 409로 덮어쓰기를 막는다. JSON을 내보내 수정 내용을 보관한 뒤 서버 버전을 다시 불러온다.

입력 미디어는 업로드 시 실제 이미지/영상 형식과 길이·크기를 검사하고 계정별 불변 asset ID로 저장한다. Worker가 결과를 가져오고 FFmpeg로 원본 오디오를 결합해 새 asset을 만든다. 일반 다운로드는 로그인과 자산 소유권을 검사한다. 외부 공급자 입력은 제한 시간의 서명 URL을 사용한다.

생성 접수는 서버에서 그래프·모델 지원·입력 자산·API 키·한도를 검증한다. 클라이언트가 계산한 순서나 경고를 신뢰하지 않는다. 확정한 graph snapshot, request_key와 각 단계의 원장을 DB에 저장한 뒤 dispatcher가 고정 Temporal Workflow ID로 시작한다. 실행 중 편집은 이미 접수한 snapshot을 바꾸지 않는다.

모달이 열린 동안 배경을 inert로 처리하고 캔버스 삭제 단축키를 비활성화한다. Tab을 대화상자 안에 유지하고 Escape로 닫은 뒤 포커스를 복원한다. 서비스 화면에서 비밀번호와 API 키는 폼 메모리에만 두고 저장 후 지운다.

오프라인 편집기는 localStorage 자동 저장과 JSON 교환을 제공한다. 이 모드의 미디어는 현재 세션 미리보기이고 서버 자산이 아니다. 실행 계획을 내보낼 수 있지만 생성 API를 호출하지 않는다.

운영 구성과 공급자 입력 계약은 [운영 가이드](operations.ko.md), [공급자 계약](provider-contract.ko.md)을 참고한다.
