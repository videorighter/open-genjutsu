# 변경 기록

버전은 Git 태그와 GitHub Release가 게시된 시점에 확정합니다. 아래 항목은 해당 버전의 릴리스 노트이며, 기록만으로 배포가 완료됐음을 의미하지 않습니다.

## Unreleased

- 생성 공급자를 OpenRouter로 통일하고 fal·Replicate·GPU Worker·Custom API(어댑터·검증·설정·API 키 등록·UI)를 제거. `GENJUTSU_MEDIA_DELIVERY`·`GENJUTSU_CUSTOM_API_URLS`·`GENJUTSU_UPLOAD_HOSTS` 설정을 삭제하고 `GENJUTSU_DOWNLOAD_HOSTS` 기본값을 빈 목록으로 변경(기존 `.env`의 이전 값은 무시).
- 모션 전이·편집 기본 모델을 `bytedance/seedance-2.5`로 변경. 참조 이미지를 인물·스타일 참조, 원본 영상을 참조 영상으로 함께 보낸다. 프로젝트 템플릿은 "모션 전이 · OpenRouter"와 "로컬 영상 테스트 · 무료".
- **추천 모델**이 선택한 노드 종류의 모델만 표시. 영상 참조 가능(Seedance 2.5·2.0·2.0 Fast, MiniMax H3, FLUX.3 Video, Runway Aleph 2.0)과 이미지→영상(Veo 3.1, Kling v3.0 Pro, Wan 3.0, Grok Imagine Video 1.5) OpenRouter 영상 모델 제공.
- 이전 fal·Replicate·GPU·Custom 노드가 있는 프로젝트는 해당 단계의 OpenRouter 기본 모델로 열린다(프롬프트 유지, 다시 저장할 때 DB 반영). 제거된 공급자의 저장 키는 표시·사용하지 않으며, 관리자 접수 ID 복구는 OpenRouter 영상 작업만 지원.
- 로컬 모션 전이·편집처럼 원본 영상을 참조하는 OpenRouter 영상 단계는 공개 HTTPS(예: Cloudflare Tunnel)가 필요. localhost의 fal/Replicate 업로드 경로는 제거됐다.

## 0.3.0-rc.2

- 게시되지 않은 0.3.0-rc.1의 변경을 포함한다. rc.1 대비 DB migration 변경은 없다.
- 무료 로컬 영상 테스트 템플릿과 본인 PC에서 총 $10 이내 실제 모델을 비교하는 안내.
- fal/Replicate 파일 API로 입력을 전달해 공개 도메인 없이 영상 모델 호출, 업로드 실패 시 생성 제출 중단.
- OpenRouter 전체 모델 목록(텍스트·이미지·영상)을 서버에서 갱신해 노드별 모델 제안과 능력 기반 검증 제공.
- OpenRouter 영상 생성(`/videos`)과 참조 이미지 생성 노드(`/images`), 영상 입력 모델의 영상 전체 분석.
- 실행 계획의 예상 비용, 작업 내역의 실제 비용 표시.
- 모든 공급자의 402(잔액 부족)·429(요청 한도) 응답을 접수되지 않은 요청으로 보고 재시도 없이 사유와 함께 실패 처리(이전에는 402가 확인 대기).
- 관리자 복구가 접수 ID가 기록된 영상 단계를 같은 ID로 다시 조회하도록 확장.
- 사라진 분석 기본 모델 `qwen/qwen3-vl-32b-instruct`를 `qwen/qwen3-vl-30b-a3b-instruct`로 교체.
- CI의 실제 Temporal 검사에 OpenRouter 영상·이미지 실행 시험 추가.

## 0.3.0-rc.1

- 단일 버전 원본, CI 검증, 승인 후 수동 릴리스와 digest 고정 배포 체계.
- Cloudflare Tunnel HTTPS 구성 및 도메인·Docker 호스트 준비 가이드.
- 공통 모델 카탈로그, Wan·Kling·VACE 프로젝트 템플릿과 모델별 입력 폼·서버 검증.
- 실제 입력 미디어 미리보기와 관리자 운영 현황·공급자 확인 대기 복구 화면.
- 릴리스 승인 규칙 누락 차단, 무료 동시 작업 검사와 전체 백업 격리 복원·Temporal 이력 검증 도구.
- 실제 유료 모델 평가·공개 HTTPS·별도 호스트 DR·베타는 준비 조건 확인 후 진행하며, 이 후보 버전 기록만으로 Release 게시나 운영 배포가 완료되지는 않는다.

## 0.2.0

- 로그인과 계정별 프로젝트·미디어 저장, 암호화된 공급자 키 관리.
- 노드별 모델·프롬프트 설정과 Temporal 작업 실행·복구·취소.
- 영상 업로드와 결과 다운로드, Docker Compose 자체 호스팅.
- 한국어 기본 README 및 영어·중국어 사용·운영 안내.
