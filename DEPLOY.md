# 배포 가이드

정적 프론트를 FastAPI가 직접 서빙하므로 **단일 웹 서비스**로 배포된다.

## 공통 준비
- `.env`는 커밋하지 않는다(이미 `.gitignore`). 시크릿은 플랫폼 대시보드에서 `ANTHROPIC_API_KEY`로 주입.
- 벡터 인덱스(`chroma_db/`)는 빌드 단계에서 `python -m scripts.build_index`로 생성된다(임베딩 모델 1회 다운로드 포함).
- **아웃바운드 네트워크 필요**: `/ask`는 Anthropic API를, `/news`는 데일리시큐 RSS·기사(og:image)를 런타임에 fetch한다. 차단/실패 시 뉴스는 빈 리스트로 안전 폴백(법령 답변엔 영향 없음). SSRF 방어로 사설/메타데이터 IP는 차단된다.
- (선택) `CORS_ALLOW_ORIGINS`(운영 도메인 제한), `CLAUDE_MODEL`, `NEWS_*` 등은 `.env`/대시보드 환경변수로 오버라이드.

## Render (Blueprint)
1. repo를 GitHub에 push (`.env` 제외).
2. Render → **New → Blueprint** → repo 선택 → [`render.yaml`](render.yaml) 자동 인식.
3. `ANTHROPIC_API_KEY` 입력 → 배포.
4. 빌드: `pip install -r requirements.txt && python -m scripts.build_index` / 실행: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.

## Railway
1. New Project → Deploy from GitHub.
2. [`Procfile`](Procfile)의 start 커맨드 사용. Variables에 `ANTHROPIC_API_KEY` 추가.
3. 빌드 후 1회 `python -m scripts.build_index` 실행(또는 build 훅에 추가).

## ⚠️ 무료 티어 메모리 주의 (정직한 한계)
런타임에 **torch + 한국어 SBERT 모델(~400MB)** 을 메모리에 올리므로, 512MB 무료 티어에서는 **OOM 가능성**이 있다. 선택지:

1. **메모리 여유 있는 티어**(≈1GB+)로 배포 — 가장 단순.
2. **경량화**: 쿼리 임베딩을 `onnxruntime`(SAC도 통과, torch보다 가벼움) + 양자화 ONNX 모델로 전환 → 런타임 footprint 축소.
3. **임베딩 API 전환**(예: Voyage) → torch 제거. 단, "로컬·무료 한국어 임베딩"이라는 강점은 포기.
4. **데모 영상 + 로컬 실행** — 빌드지시서가 제시한 대안. 포트폴리오엔 영상/스크린샷으로도 충분.

> 빌드 시 `chroma_db/`를 함께 커밋해 두면 배포 빌드에서 재인덱싱을 건너뛸 수 있다(단 `.gitignore`에서 제외 필요).
