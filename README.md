# agent-collab

**Claude Code** + **OpenAI Codex CLI** 협업 오케스트레이터

목표를 입력하면 자동으로 서브태스크를 분해하고 Claude와 Codex에 역할을 분배합니다.
AI 연구 전용 모드에서는 6단계 연구 루프를 지정한 라운드 수만큼 반복하며 모델을 점진적으로 발전시킵니다.
세션은 자동 저장되어 중단 후에도 이어서 재개할 수 있습니다.
프롬프트에서 `/path/to/file.py`를 직접 참조하면 파일 내용이 에이전트에게 자동으로 전달됩니다.

---

## 목차

1. [설치](#설치)
2. [모드 개요](#모드-개요)
3. [파일 참조](#파일-참조)
4. [목표 기반 플래닝 모드](#목표-기반-플래닝-모드)
5. [에이전트 직접 지정 모드](#에이전트-직접-지정-모드)
6. [AI 연구 모드](#ai-연구-모드)
7. [세션 관리](#세션-관리)
8. [출력 형식](#출력-형식)
9. [옵션 레퍼런스](#옵션-레퍼런스)
10. [파일 구조](#파일-구조)

---

## 설치

### GitHub에서 직접 설치 (권장)

```bash
pip install git+https://github.com/crimama/agent-collab.git
```

### 로컬 클론 후 설치

```bash
git clone https://github.com/crimama/agent-collab.git
cd agent-collab
pip install -e .
```

설치 후 `collab` 명령어가 전역으로 등록됩니다.

### 요구사항

- Python 3.9+
- [Claude Code CLI](https://claude.ai/code) 설치 및 로그인
- [OpenAI Codex CLI](https://github.com/openai/codex) 설치 (`npm install -g @openai/codex`)

---

## 모드 개요

| 모드 | 진입 방법 | 설명 |
|------|-----------|------|
| 목표 기반 플래닝 | `collab "목표"` | 목표 → 플랜 생성 → 검토·수정 → 실행 |
| 에이전트 직접 지정 | `collab --claude` / `--codex` | 플래닝 없이 단일 에이전트로 즉시 실행 |
| 병렬 비교 | `collab --parallel` | Claude와 Codex가 동시에 같은 태스크 수행 |
| AI 연구 모드 | `collab research "목표"` | 6단계 연구 루프를 N 라운드 반복 |
| 대화형 REPL | `collab -i` | 명령어 프리픽스로 실시간 전환 |
| 세션 목록 | `collab sessions` | 저장된 세션 전체 조회 |
| 세션 재개 | `collab resume` | 중단된 세션 선택 후 이어서 실행 |

---

## 파일 참조

프롬프트 어디서나 파일을 참조하면 내용이 에이전트 컨텍스트에 자동 첨부됩니다.

### 두 가지 참조 방식

| 문법 | 설명 | 예시 |
|------|------|------|
| `/절대경로/파일.py` | 절대/상대 경로로 직접 지정 | `/src/auth.py` |
| `@파일명.py` | cwd에서 파일명으로 재귀 검색 | `@auth.py` |

```bash
# 절대 경로 참조
collab --claude "Review /src/auth.py and suggest improvements"

# @ 단축 참조 (cwd에서 auth.py를 자동으로 찾음)
collab --claude "Review @auth.py and fix the JWT bug"

# 여러 파일 동시 참조
collab --parallel "Compare /src/v1.py and /src/v2.py"

# AI 연구 모드
collab research "Improve @lora.py performance"
```

첨부 시 알림 표시:

```
  📎 2 file(s) attached: auth.py, test_auth.py
```

### REPL에서 Tab 자동완성

`collab -i` 대화형 모드에서 `/path` 및 `@name` 입력 후 `Tab`으로 자동완성합니다.

```
▶ Fix /src/au[Tab]  →  /src/auth.py
▶ Review @lo[Tab]   →  @lora.py
```

### 동작 방식

| 항목 | 내용 |
|------|------|
| `/path` 패턴 | 절대/상대 경로, 확장자 필수 |
| `@name` 패턴 | cwd 재귀 검색, 이름 또는 부분 경로 |
| 파일 크기 제한 | 파일당 최대 32KB |
| 첨부 위치 | 원본 프롬프트 뒤 fenced code block |
| 지원 언어 | Python, JS/TS, Bash, Rust, Go 등 20+ |
| 미존재 경로 | 무시됨 (오류 없음) |

---

## 목표 기반 플래닝 모드

자연어로 목표를 입력하면 Claude가 서브태스크로 분해하고
각 태스크에 적합한 에이전트를 자동으로 배정합니다.

### 기본 실행

```bash
collab "FastAPI로 JWT 인증이 포함된 REST API를 만들어줘"
collab "기존 auth.py를 리팩토링하고 테스트 코드를 작성해줘"
collab "CSV 데이터를 PostgreSQL에 적재하는 파이프라인 구현"
```

### 실행 흐름

```
목표 입력
    │
    ▼
Claude가 서브태스크 분해 + 에이전트 배정
    │
    ▼
플랜 미리보기 (대화형 편집기)
    │
    ├─ Enter / go  → 실행
    ├─ r 2 claude  → 태스크 2를 Claude로 변경
    ├─ e 3         → 태스크 3 프롬프트 직접 편집
    ├─ d 5         → 태스크 5 삭제
    ├─ a           → 새 태스크 추가
    └─ q           → 취소
    │
    ▼
각 태스크 순서 실행 (의존성 자동 보장)
    │
    ▼
결과 저장 → collab_results_*.md
```

### 플랜 편집기 명령어

| 명령어 | 설명 |
|--------|------|
| `Enter` \| `go` | 플랜 실행 |
| `r <n> <agent>` | 태스크 n의 에이전트 변경 (`claude` \| `codex`) |
| `e <n>` | 태스크 n의 프롬프트 직접 편집 |
| `v <n>` | 태스크 n의 전체 프롬프트 보기 |
| `d <n>` | 태스크 n 삭제 |
| `a` | 새 태스크 추가 |
| `p <n>` | 태스크 n 병렬 실행 토글 |
| `dep <n> <ids>` | 의존성 설정 (예: `dep 3 1 2`) |
| `verbose` | 프롬프트 표시 토글 |
| `q` | 취소 |

### 플랜만 확인 (실행 없이)

```bash
collab --plan-only "마이크로서비스 아키텍처 설계"
```

### 작업 디렉토리 지정

```bash
collab --cwd /my/project "Add error handling to all API endpoints"
```

---

## 에이전트 직접 지정 모드

플래닝 없이 에이전트를 직접 지정해 즉시 실행합니다.

### Claude Code 전용

복잡한 추론, 분석, 아키텍처 설계, 코드 리뷰, 문서화에 적합합니다.

```bash
collab --claude "NF 모델이 catastrophic forgetting을 방지하는 메커니즘 분석"
collab --claude "현재 코드베이스의 병목 지점을 찾고 개선 방안 제시"
collab --claude "이 논문의 실험 섹션에서 부족한 부분 리뷰"
```

### Codex CLI 전용

코드 생성, 테스트 작성, 보일러플레이트, 빠른 구현에 적합합니다.

```bash
collab --codex "User 모델에 대한 CRUD API 엔드포인트 생성"
collab --codex "auth.py에 대한 pytest 테스트 코드 작성"
collab --codex "기존 for 루프를 벡터화된 numpy 연산으로 변환"
```

### 병렬 비교 (둘 다 동시 실행)

같은 태스크에 대해 두 에이전트의 결과를 비교하고 싶을 때 사용합니다.

```bash
collab --parallel "OAuth2 로그인 플로우 구현"
collab --parallel "이 알고리즘의 시간복잡도를 줄이는 방법"
```

### 대화형 REPL

```bash
collab -i
```

REPL은 대화 히스토리를 기억하며, 이전 대화 컨텍스트를 자동으로 다음 요청에 주입합니다.

#### 에이전트 명령어

| 프리픽스 | 설명 |
|----------|------|
| (없음) | 목표 → 플랜 → 실행 |
| `/claude <task>` | Claude Code 직접 호출 (히스토리 주입) |
| `/codex <task>` | Codex CLI 직접 호출 (히스토리 주입) |
| `/parallel <task>` | 두 에이전트 동시 실행 + 비판자 |
| `/plan <goal>` | 플랜만 생성 (실행 X) |

#### 세션 관리 명령어

| 명령어 | 설명 |
|--------|------|
| `/help` | 전체 명령어 도움말 |
| `/clear` | 화면 지우기 + 대화 히스토리 초기화 |
| `/history` | 최근 대화 기록 보기 |
| `/status` (`/s`) | 세션 상태 (cwd, 히스토리 수, 토큰 추정치) |
| `/compact` | 출력 압축 모드 토글 (25줄 미리보기) |
| `/copy` | 마지막 에이전트 출력을 클립보드에 복사 |
| `/quit` | 종료 |

#### 기타 UX 기능

- **토큰 카운터**: 프롬프트에 `[~Nt]`로 현재 컨텍스트 토큰 추정치 표시
- **멀티라인 입력**: `"""`로 시작해 여러 줄 입력, `"""`로 종료
- **신택스 하이라이팅**: 에이전트 출력의 코드 블록 자동 컬러링
- **Tab 자동완성**: `/path`와 `@filename` 경로 자동완성

```
▶ /claude """
  (multi-line — end with """ on a blank line)
  … Fix the auth bug in @auth.py
  … Make sure all tests in @test_auth.py pass
  … """
  📎 2 file(s) attached: auth.py, test_auth.py
  [~142t] ▶
```

---

## AI 연구 모드

AI 모델 개발을 위한 **6단계 연구 루프**를 N 라운드 반복합니다.
각 라운드의 결론이 다음 라운드의 컨텍스트로 자동 전달됩니다.

### 라운드 구조

```
┌──────────────────────────────────────────────────────────────┐
│  Step 1  Goal Understanding       Claude  (1개)              │
│          ↓                                                   │
│  Step 2  Problem Analysis         Claude × N  ── 병렬        │
│          ↓ (합성)                                            │
│  Step 3  Methodology + Impl.      Claude(설계) + Codex × N  │
│          ↓                                ── 병렬            │
│  Step 4  Experiment Execution     Codex × N  ── 병렬         │
│          ↓                                                   │
│  Step 5  Result Analysis          Claude  (1개)              │
│          ↓                                                   │
│  Step 6  Conclusion               Claude → 다음 Round 전달   │
└──────────────────────────────────────────────────────────────┘
          ↓  next_hypotheses 자동 carry-over
          Round 2 → Round 3 → ...
```

### 기본 실행

```bash
# 3라운드 (기본값)
collab research "MVTec 이상 탐지에서 Pixel AP를 5% 향상시켜라"

# 라운드 수 지정
collab research --rounds 5 "Continual learning forgetting 문제 해결"
```

### 병렬 에이전트 수 조절

각 Step에서 동시에 실행할 에이전트 수를 개별 조정할 수 있습니다.

```bash
collab research \
  --rounds 3 \
  --analysts 3 \       # Step 2: Claude 분석가 수
  --implementers 3 \   # Step 3: Codex 구현자 수
  --experiments 4 \    # Step 4: Codex 실험 수
  "LoRA rank 최적화로 성능 향상"
```

| 옵션 | 기본값 | Step | 역할 |
|------|--------|------|------|
| `--analysts N` | 2 | Step 2 | 서로 다른 관점으로 문제 분석 |
| `--implementers N` | 2 | Step 3 | 서로 다른 구현 방법 시도 |
| `--experiments N` | 2 | Step 4 | 서로 다른 설정으로 실험 병렬 실행 |

### 중단된 세션 재개

매 Step마다 `research_state.json`이 자동 저장되므로
중간에 중단되어도 이어서 진행할 수 있습니다.

```bash
# research_state.json 경로를 직접 지정
collab research --resume research_state.json

# 또는 collab resume 으로 대화형 선택 (아래 세션 관리 참고)
collab resume
```

### 플랜만 확인

```bash
collab research --plan-only --rounds 5 "목표"
```

### 작업 디렉토리 지정

에이전트가 실제 코드를 읽고 수정할 디렉토리를 지정합니다.

```bash
collab research --cwd /Volume/MoLeFlow --rounds 3 \
  "Pixel AP를 58% → 62%로 향상"
```

### 자동 저장 파일

| 파일 | 저장 시점 | 내용 |
|------|-----------|------|
| `research_state.json` | 매 Step 완료 시 | 전체 세션 상태 (재개 가능) |
| `research_report_*.md` | 세션 종료 시 | 모든 라운드 결과 마크다운 리포트 |

---

## 세션 관리

모든 `collab` 실행은 자동으로 세션으로 저장됩니다 (`~/.collab/sessions/`).
네트워크 오류나 예기치 않은 종료 후에도 중단된 지점부터 이어서 실행할 수 있습니다.

### 세션 목록 보기

```bash
collab sessions
# 또는
collab ls
```

출력 예시:

```
   #  Type        Updated           Goal                                                    Progress      Status
  ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
   1  PLANNING    2024-01-15 14:23  FastAPI로 JWT 인증이 포함된 REST API를 만들어줘         3/5 tasks     in progress
   2  RESEARCH    2024-01-15 11:08  MVTec Pixel AP 5% 향상                                Round 2/3     completed
   3  PLANNING    2024-01-14 22:41  기존 auth.py 리팩토링                                  5/5 tasks     completed
```

### 세션 재개

```bash
# 대화형 목록에서 번호로 선택
collab resume

# 세션 ID를 직접 지정
collab resume <session-id>
```

재개 시 동작:
- **플래닝 세션**: 이미 완료된 태스크는 건너뛰고, 그 출력을 컨텍스트로 주입하여 나머지 태스크만 실행
- **연구 세션**: 완료된 라운드 이후부터 재개

### 세션 삭제

`collab resume` 대화형 모드에서 `d <번호>` 로 삭제할 수 있습니다.

```
resume> d 2
Delete 'MVTec Pixel AP 5% 향상'? (y/N) y
Deleted.
```

---

## 출력 형식

각 태스크 결과는 터미널에서 깔끔하게 미리보기 형식으로 출력됩니다.

```
  ✓ [CLAUDE]  아키텍처 분석  4.2s  [2/5]
  ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
  분석 결과 첫 번째 줄
  분석 결과 두 번째 줄
  ...
  ╌╌ +42 more lines (saved to results file) ╌╌
```

- 출력이 긴 경우 처음 **18줄**만 미리보기로 표시
- 120자를 초과하는 줄은 자동으로 잘려서 표시
- 전체 출력은 `collab_results_*.md` 파일에 저장
- AI 연구 모드는 `research_report_*.md` 파일에 저장

---

## 옵션 레퍼런스

### `collab` (기본 오케스트레이터)

```
collab [옵션] "목표 또는 태스크"

옵션:
  --claude          Claude Code 강제 지정 (플래닝 없이 즉시 실행)
  --codex           Codex CLI 강제 지정 (플래닝 없이 즉시 실행)
  --parallel        두 에이전트 동시 실행 후 결과 비교
  --plan-only       플랜만 생성, 실행하지 않음
  --cwd <path>      에이전트 작업 디렉토리 (기본: 현재 디렉토리)
  -i, --interactive 대화형 REPL 모드
  -v, --verbose     상세 출력
```

### `collab research` (AI 연구 모드)

```
collab research [옵션] "연구 목표"

옵션:
  --rounds N          라운드 수 (기본: 3)
  --analysts N        Step 2 병렬 Claude 분석가 수 (기본: 2)
  --implementers N    Step 3 병렬 Codex 구현자 수 (기본: 2)
  --experiments N     Step 4 병렬 Codex 실험 수 (기본: 2)
  --cwd <path>        작업 디렉토리 (기본: 현재 디렉토리)
  --resume <path>     research_state.json에서 세션 재개
  --plan-only         라운드 구조만 출력, 실행하지 않음
```

### `collab sessions` / `collab ls`

```
collab sessions     저장된 모든 세션 목록 출력
collab ls           동일 (단축 별칭)
```

### `collab resume`

```
collab resume [session-id]

  session-id 생략 시: 대화형 목록 표시
  session-id 지정 시: 해당 세션 즉시 재개

대화형 모드 명령어:
  <number>    해당 세션 재개
  d <number>  해당 세션 삭제
  q           취소
```

---

## 파일 구조

```
agent-collab/
├── pyproject.toml            # pip 패키지 설정
├── agent_collab/
│   ├── cli.py                # 메인 진입점 (collab 명령어)
│   ├── planner.py            # Claude를 사용한 태스크 분해
│   ├── plan_ui.py            # 대화형 플랜 편집기
│   ├── executor.py           # 태스크 실행 엔진 (의존성 순서 보장)
│   ├── file_ref.py           # /path/to/file 참조 확장 유틸리티
│   ├── session_store.py      # 세션 자동 저장 (~/.collab/sessions/)
│   ├── resume_ui.py          # 세션 재개 대화형 UI
│   ├── config.yaml           # 에이전트 설정 및 라우팅 규칙
│   ├── agents/
│   │   ├── claude_agent.py   # Claude Code CLI 래퍼
│   │   └── codex_agent.py    # OpenAI Codex CLI 래퍼
│   └── research/
│       ├── research_mode.py  # AI 연구 모드 진입점
│       ├── steps.py          # 6단계 Step 실행 로직 및 프롬프트
│       ├── parallel_pool.py  # 병렬 에이전트 풀
│       ├── state.py          # 라운드 간 상태 관리
│       └── display.py        # 터미널 출력 및 UI
└── ~/.collab/sessions/       # 자동 저장 세션 디렉토리
    └── {session-id}/
        └── session.json
```

---

## 에이전트 역할 분담 기준

| Claude Code | Codex CLI |
|-------------|-----------|
| 아키텍처 설계 및 검토 | 코드 생성 및 구현 |
| 복잡한 추론과 분석 | 테스트 코드 작성 |
| 문제 원인 파악 | 보일러플레이트 생성 |
| 논문·문서 작성 | 실험 스크립트 실행 |
| 전략 및 방향 수립 | 반복적인 코드 변환 |
