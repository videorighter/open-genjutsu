# 모델 공급자 연결

## 실행 가능한 경로

| 단계 | 공급자 | 입력과 동작 |
| --- | --- | --- |
| 원본 영상·참조 이미지 | Local / media-input | 업로드한 계정 소유 자산 |
| 장면 분석 | OpenRouter 또는 OpenAI 호환 Custom | 원본 영상에서 추출한 3개 JPEG 프레임과 노드 지시 |
| 프롬프트 설계 | OpenRouter 또는 OpenAI 호환 Custom | 노드 지시와 연결된 텍스트 결과 |
| 모션 전이·편집 | fal | Wan-Animate move/replace, Wan VACE, Kling v3 Motion Control의 명시적 입력 매핑 |
| 모션 전이·편집 | Replicate | `owner/model`의 prediction API, 사용자 지정 입력 JSON |
| 모션 전이·편집 | Custom/GPU | 아래 비동기 작업 계약 |
| 결과 내보내기 | Local / ffmpeg | 입력 영상 인코딩과 원본 오디오 결합 |

API 키와 endpoint는 서버에서 처리한다. 모델 ID와 프롬프트 변경은 새 실행 snapshot에 적용되며 이미 접수한 작업에는 적용되지 않는다. 모델마다 지원하는 옵션이 다르다. 공급자의 실제 모델 가용성과 요금은 공급자에서 확인한다.

기본 프로젝트는 원본 영상·참조 이미지·Wan-Animate·출력 4단계다. Wan-Animate는 자유 프롬프트를 받지 않으므로 기본 프로젝트에 효과 없는 유료 LLM 단계를 넣지 않는다. 프롬프트 중심 생성은 분석/프롬프트 노드를 추가하고 VACE 또는 해당 입력을 지원하는 Custom/GPU 모델을 연결한다. 언어 모델 노드의 기본 후보는 Dolphin이며 모델 ID를 바꿀 수 있다. 공급자 정책이 무조건 관대하다고 보장하지 않는다.

## 공급자 입력 JSON

알려진 모델 입력은 `models/catalog.json`을 UI와 서버가 함께 사용한다. Kling은 방향 기준(video/image)과 원본 오디오 유지, VACE는 작업 종류·추론 단계(2~50)·guidance(1~10)·inpainting 마스크 URL을 폼으로 편집한다. Kling image 방향 기준은 10초 이하의 연결 원본 영상을 사용한다. 공급자 문서 확인과 실제 생성 검증은 별개이며 카탈로그에 각각 기록한다. 목록 밖의 모델과 입력 JSON은 계속 사용할 수 있다.

노드 설정의 JSON 객체에서 모델별 옵션을 지정한다. `$video`, `$image`, `$images`, `$prompt` 문자열은 각각 첫 연결 영상 URL, 첫 참조 이미지 URL, 참조 이미지 URL 배열, 노드 지시와 이전 텍스트 결과로 대체한다.

Replicate는 모델마다 필드명이 달라 기본 입력을 추정해 보내지 않는다. 해당 모델의 공식 schema에 맞춰 지정한다.

```json
{"video":"$video","reference_image":"$image","prompt":"$prompt","seed":42}
```

이 예시의 필드명이 모든 Replicate 모델에서 유효한 것은 아니다. 모델 schema에 맞게 바꾼다. hosted prediction의 접수 ID를 저장하고 `/predictions/{id}`로 상태를 조회한다.

fal Wan-Animate는 image/video URL, seed와 지원 해상도를 사용하고 프롬프트는 경고 후 보내지 않는다. VACE는 기본 `task: pose`이며, inpainting은 모델 schema에 맞는 `mask_video_url` 또는 `mask_image_url`을 JSON에 지정해야 한다. 이 버전에는 마스크 페인팅 UI가 없다. 지원 모델의 필수 image/video 입력은 서버 연결 자산으로 고정한다.

OpenAI 호환 API는 base URL 아래 `POST /chat/completions`을 제공해야 한다. `model`, `messages`, `temperature`, `max_tokens`, `stream:false`를 사용한다. `max_tokens`는 입력 JSON에서 1~4096으로 제한한다. 분석은 영상 전체가 아닌 샘플 프레임을 읽는다.

## Custom/GPU 비동기 계약

운영자가 base URL과 결과 CDN 호스트를 허용하고, 사용자가 같은 base URL에 키를 등록한다. 요청 인증은 `Authorization: Bearer <key>`다. TLS가 필요하다.

```text
POST {base}/jobs
```

```json
{
  "model":"zai-org/SCAIL-2",
  "task":"motion",
  "prompt":"Preserve the source motion",
  "video_url":"https://studio.example.com/api/assets/…/content?…",
  "image_url":"https://studio.example.com/api/assets/…/content?…",
  "parameters":{"temperature":0.7,"seed":"42","resolution":"720p"}
}
```

`parameters`에 공급자 입력 JSON 옵션도 합쳐진다. 서버가 반환해야 하는 접수 응답:

```json
{"request_id":"opaque-safe-job-id"}
```

접수 ID는 URL path에 사용하므로 영문·숫자·하이픈·밑줄 형태를 권장한다. 서버가 durable하게 접수한 후 응답해야 한다. 제출 응답 유실 시 중복 POST를 자동으로 보내지 않는다.

```text
GET {base}/jobs/{request_id}
POST {base}/jobs/{request_id}/cancel
```

상태 조회 응답 예시:

```json
{"status":"IN_QUEUE"}
```

```json
{"status":"COMPLETED","video_url":"https://approved-cdn.example.com/result.mp4"}
```

실패/취소는 `FAILED` 또는 `CANCELLED`다. 취소 POST는 접수 여부만 응답하며 최종 상태는 GET으로 확인한다. 결과 URL은 승인 CDN의 HTTPS 영상이어야 한다. 결과는 검사·저장한 후 계정 전용 파일로 제공한다.

이 저장소에는 SCAIL-2나 SteadyDancer의 GPU 모델 로딩·추론 서버가 포함되지 않는다. 이 계약을 구현한 모델 서버를 별도로 운영한다. 원본 파일과 결과 크기·길이는 서비스 업로드 제한을 지켜야 한다.
