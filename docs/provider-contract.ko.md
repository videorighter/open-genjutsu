# 모델 공급자 연결

## 실행 가능한 경로

| 단계 | 공급자 | 입력과 동작 |
| --- | --- | --- |
| 원본 영상·참조 이미지 | Local / media-input | 업로드한 계정 소유 자산 |
| 장면 분석 | OpenRouter chat completions | 원본 영상에서 추출한 3개 JPEG 프레임 또는 영상 전체(영상 입력 모델, `analysis_input: video`)와 노드 지시 |
| 프롬프트 설계 | OpenRouter chat completions | 노드 지시와 연결된 텍스트 결과 |
| 이미지 생성 | OpenRouter `/images` | 노드 지시·연결 텍스트와 참조 이미지로 PNG 자산 생성 |
| 모션 전이·편집 | OpenRouter `/videos` | 인물·스타일 참조 또는 첫/마지막 프레임 이미지, 원본 영상 참조(지원 모델, 공개 HTTPS 필요) |
| 결과 내보내기 | Local / ffmpeg | 입력 영상 인코딩과 원본 오디오 결합 |

생성 단계는 OpenRouter만 사용하며 공급자는 노드 종류별로 고정된다. API 키는 서버에서 처리한다. 모델 ID와 프롬프트 변경은 새 실행 snapshot에 적용되며 이미 접수한 작업에는 적용되지 않는다. 모델마다 지원하는 옵션이 다르다. 실제 모델 가용성과 요금은 OpenRouter에서 확인한다.

기본 모델은 `models/catalog.json`의 `defaults` 한 곳에서 정한다. 분석 `qwen/qwen3-vl-30b-a3b-instruct`, 프롬프트 `cognitivecomputations/dolphin-mistral-24b-venice-edition`, 이미지 `qwen/qwen-image-3`, 모션 전이·편집 `bytedance/seedance-2.5`다. 기본 프로젝트는 원본 영상·참조 이미지·모션 전이·출력 4단계이며 유료 LLM 단계를 넣지 않는다. 모션 노드는 기본으로 참조 이미지를 인물·스타일 참조(`image_mode: "reference"`)로, 원본 영상을 참조 영상으로 함께 보내고, 참조 인물이 원본 영상의 동작·카메라·타이밍을 따르도록 하는 기본 프롬프트를 사용한다. 각 노드의 모델 ID는 바꿀 수 있다. 공급자 정책이 무조건 관대하다고 보장하지 않는다.

이전에 fal·Replicate·GPU·Custom 노드로 저장한 프로젝트는 읽을 때 해당 단계의 OpenRouter 기본 모델로 변환한다. 공급자 전용 옵션과 endpoint는 버리고 프롬프트는 유지한다. DB는 프로젝트를 다시 저장할 때 바뀐다. 실행 계획과 접수도 저장된 그래프를 먼저 변환하므로 OpenRouter 기본값으로 실행한다. 제거된 공급자로 저장한 키는 표시·사용하지 않으며 삭제하지 않는다.

## 입력 전달

`GENJUTSU_PUBLIC_URL`이 공개 HTTPS이면 Worker는 만료되는 서비스 입력 URL(서명 URL)로 OpenRouter에 입력 미디어를 전달한다. 공개 HTTPS가 없으면 참조 이미지와 영상 전체 분석 입력을 data URL로 요청에 포함한다(파일당 `GENJUTSU_MAX_INLINE_MEDIA_MB`, 기본 20MB 이하, 초과 시 요청 전에 실패). 분석 샘플 프레임은 항상 요청 본문에 포함한다.

OpenRouter 영상 생성은 영상 참조를 공개 HTTPS URL로만 받는다. data URL은 거절하고 `/files`는 영상을 받지 않는다. 따라서 공개 HTTPS가 없으면(예: `http://localhost`) 원본 영상이 연결된 OpenRouter 영상 단계는 서버 검증이 막고 공개 HTTPS(예: [Cloudflare Tunnel](cloudflare-staging.ko.md))로 실행하라고 안내한다. 이미지만 입력하는 영상 생성은 localhost에서도 실행된다. [로컬 실행과 실제 모델 평가](local-testing.ko.md)를 참고한다.

## OpenRouter 이미지·영상

모델 목록과 능력은 `GET /api/v1/models?output_modalities=all`, `/videos/models`, `/images/models`에서 서버가 받아 `GENJUTSU_CATALOG_TTL_SECONDS`(기본 6시간)마다 갱신한다. 목록을 확인하지 못하면 유료 이미지·영상 단계는 실행하지 않고, 텍스트 단계는 경고 후 실행한다. 영상 모델의 해상도·길이·화면 비율·참조 이미지 사용 방식은 모델이 지원하는 값만 선택할 수 있으며, 실행 계획과 접수 모두 기본값을 고정한 snapshot을 검증하고 그 snapshot을 실행해 예상 비용과 실제 요청을 일치시킨다. seed를 지원하지 않는 모델에는 seed를 보내지 않는다.

- 이미지: `POST /images`를 동기 호출하고 `data[0].b64_json`을 PNG 자산으로 저장한다. 응답 후 저장에 실패하면 이미 과금됐을 수 있으므로 공급자 확인 대기로 남긴다.
- 영상: `POST /videos` 접수 ID(`gen-vid-…`)를 저장하고 `GET /videos/{id}`로 조회한다. 결과 `GET /videos/{id}/content`는 서명 URL이 아니므로 OpenRouter 호스트에만 키를 붙여 받고, 다른 호스트로 키를 보내지 않는다. 리다이렉트는 `GENJUTSU_DOWNLOAD_HOSTS`(기본 빈 목록)에 허용한 호스트만 따른다. 결과는 약 24시간 뒤 만료된다.
- OpenRouter 영상 API에는 **취소가 없다.** 취소 요청 후에도 최종 상태까지 조회하고 후속 단계는 실행하지 않는다.
- 402(잔액 부족)·429(요청 한도)는 접수되지 않은 요청으로 보고 실패 처리하며 자동 재시도하지 않는다. 그 밖의 4xx 거절과 접수 후 실패에는 공급자가 보낸 사유를 단계 오류에 함께 기록하고 작업 내역에 표시한다. OpenRouter가 `HTTP 400: {…}`로 감싼 상위 모델 메시지를 꺼내 쓰며, URL(서명 토큰 포함)과 키 형태 문자열은 지우고 300자로 자른다.
- Seedance 2.5 참조 영상 제약(2026-10-13 실측): 영상 화소 수가 407,696 이상이어야 하며(848×480은 거절, 854×480은 통과), 실제 인물로 보이는 참조 영상은 `InputVideoSensitiveContentDetected.PrivacyInformation`으로 거절한다. 사실적으로 생성한 인물 영상도 거절됐다. 두 경우 모두 접수 전 거절이라 접수 ID가 없다. 응답의 `usage.cost`를 단계 결과에 기록한다. 카탈로그 가격으로 계산한 실행 전 금액은 추정치다. 초당 영상 가격·최소 청구액·입력 이미지당 가격만 계산하며, 토큰 단가(Seedance의 `video_tokens` 등)나 `duration_seconds*` 같은 SKU는 예상 불가로 표시한다. 실제 비용은 실행 후 단계별로 표시한다.

## 공급자 입력 JSON

알려진 모델 입력은 `models/catalog.json`을 UI와 서버가 함께 사용한다. **추천 모델**은 선택한 노드 종류의 모델만 보여준다. 추천 영상 모델 중 영상 참조가 가능해 모션 전이에 쓸 수 있는 모델은 Seedance 2.5, Seedance 2.0, Seedance 2.0 Fast, MiniMax H3(`minimax/hailuo-3`), FLUX.3 Video, Runway Aleph 2.0(영상 편집)이다. Veo 3.1, Kling v3.0 Pro, Wan 3.0, Grok Imagine Video 1.5는 이미지→영상만 지원한다. 목록 밖 OpenRouter 모델도 ID로 입력할 수 있으며(실시간 카탈로그 자동 완성), 서버가 카탈로그의 능력으로 검증한다. 공급자 문서 확인과 실제 생성 검증은 별개이며 카탈로그에 각각 기록한다.

노드 설정의 JSON 객체에서 모델별 옵션을 지정한다. 분석·프롬프트는 `max_tokens`(1~4096, 기본 1024)와 분석의 `analysis_input: video`, 이미지는 `aspect_ratio`, 영상은 모델이 지원하는 `resolution`·`duration`·`aspect_ratio`·`generate_audio`·`image_mode`(`reference`, `first_frame`, `first_last`)를 사용한다. 영상 모델이 지원하지 않는 항목은 서버 검증이 거절한다.

텍스트 단계는 OpenRouter `POST /chat/completions`에 `model`, `messages`, `temperature`, `max_tokens`, `stream:false`를 보낸다. 분석은 기본으로 샘플 프레임 3개를, `analysis_input: video`이면 영상 전체를 보낸다.
