# aws-blog-skills 규칙 업데이트 (2026-09-20)

로컬 원본 `~/my-project/aws-blog/plugins/aws-blog-skills/skills/aws-blog-skills/references/`에 이미 반영했습니다.
플러그인 캐시에 반영하려면 `claude plugin update aws-blog-skills@aws-blog`를 실행합니다.

## structure.md — 확인된 카테고리 경로 추가

| 표시 이름 | 경로 |
|---|---|
| Artificial Intelligence | `https://aws.amazon.com/ko/blogs/tech/category/artificial-intelligence/` |
| Amazon Bedrock | `https://aws.amazon.com/ko/blogs/tech/category/artificial-intelligence/amazon-machine-learning/amazon-bedrock/` |
| Amazon Bedrock AgentCore | `https://aws.amazon.com/ko/blogs/tech/category/artificial-intelligence/amazon-machine-learning/amazon-bedrock/amazon-bedrock-agentcore/` |
| Strands Agents | `https://aws.amazon.com/ko/blogs/tech/category/artificial-intelligence/strands-agents/` |

`artificial-intelligence/amazon-bedrock/`(amazon-machine-learning 없이)는 404입니다.

## structure.md — 금액 표기 예외

- 1센트 미만 금액이 표의 주된 값이면 소수 넷째 자리까지 적고 캡션에 명시한다.

## style.md — lint 오탐 처리

- `돌아가` 규칙에 "질문으로 돌아가겠습니다"가 걸리면 "질문에 답하겠습니다"로 바꾼다.
- 다이어그램 주석에도 표 번호 하드참조와 화살표 문자를 쓰지 않는다.

## diagrams.md — Claude Code 로컬 실행

- 작업 폴더 `blog/<YYYY-MM-DD>-<slug>/`, 출력 `out/<slug>/`와 `out/<slug>.zip`.
- Playwright는 uv 가상 환경에 설치, `~/.cache/ms-playwright` chromium 재사용.
- Ember 폰트/AWS 아이콘 부재 시 Noto Sans CJK KR 폴백, 아이콘 없는 노드.
- 막대 차트 `bar()` 헬퍼와 4px 그리드 눈금 규칙, 기준선 라벨 충돌 시 범례로 이동.

## diagrams.md — 원본 저장 위치 (사용자 확정)

- 블로그 작성 후 첫 원본(Markdown, images/, zip)은 항상 현재 프로젝트 디렉터리 하위 `source-doc/`에 저장한다.
