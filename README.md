# agent-collab

**Claude Code** + **OpenAI Codex CLI** 협업 오케스트레이터

목표를 입력하면 자동으로 서브태스크를 분해하고 Claude와 Codex에 역할을 분배합니다.
AI 연구 전용 모드에서는 6단계 연구 루프를 지정한 라운드 수만큼 반복하며 모델을 점진적으로 발전시킵니다.
병렬 실행 시 비판자(Critic) 에이전트가 자동으로 결과를 검토합니다.
세션은 자동 저장되어 중단 후에도 이어서 재개할 수 있습니다.
프롬프트에서 `/path/to/file.py` 또는 `@filename.py`로 파일을 참조하면 내용이 자동으로 첨부됩니다.

## 🚀 Quick Start

```bash
# 1. 설치
pip install git+https://github.com/crimama/agent-collab.git

# 2. 시작 (그냥 collab만 입력!)
collab

# Interactive REPL이 자동으로 시작됩니다
╭─────────────────────────────────────────────────╮
│  agent-collab  (Claude ↔ Codex CLI)             │
│  Interactive mode - Type /help for commands     │
╰─────────────────────────────────────────────────╯

  @file.py  attach  │  @pattern?  select file  │  @?pattern  search files
  """  multi-line  │  Tab  autocomplete  │  /help  commands

▶ Build a REST API with JWT auth and tests
```

**그게 전부입니다!** `collab` 명령어만 입력하면 interactive mode가 바로 시작됩니다.

---

## 목차

1. [설치](#설치)
2. [모드 개요](#모드-개요)
3. [파일 참조](#파일-참조)
4. [목표 기반 플래닝 모드](#목표-기반-플래닝-모드)
5. [에이전트 직접 지정 모드](#에이전트-직접-지정-모드)
6. [비판자 에이전트](#비판자-에이전트)
7. [AI 연구 모드](#ai-연구-모드)
8. [세션 관리](#세션-관리)
9. [출력 형식](#출력-형식)
10. [옵션 레퍼런스](#옵션-레퍼런스)
11. [파일 구조](#파일-구조)

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
| 🌟 **대화형 REPL (기본)** | `collab` | 명령어 프리픽스로 실시간 전환 **(기본 모드)** |
| 목표 기반 플래닝 | `collab "목표"` | 목표 → 플랜 생성 → 검토·수정 → 실행 |
| 에이전트 직접 지정 | `collab --claude` / `--codex` | 플래닝 없이 단일 에이전트로 즉시 실행 |
| 병렬 비교 | `collab --parallel` | Claude와 Codex가 동시에 같은 태스크 수행 |
| AI 연구 모드 | `collab research "목표"` | 6단계 연구 루프를 N 라운드 반복 |
| 세션 목록 | `collab sessions` | 저장된 세션 전체 조회 |
| 세션 재개 | `collab resume` | 중단된 세션 선택 후 이어서 실행 |

**💡 Quick Start:** 그냥 `collab` 입력하면 interactive REPL이 시작됩니다!

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

### 파일 검색 및 자동완성

#### 1. 파일 후보군 보기

`@?<pattern>` 또는 `/files <pattern>` 명령어로 파일 후보군을 조회:

```bash
# REPL에서
▶ @?auth

  📁 Found 3 file(s) matching 'auth':

  ./
    auth.py                                  (2.3KB)       → @auth.py
    auth_test.py                             (1.1KB)       → @auth_test.py

  src/
    auth_handler.py                          (5.4KB)       → src/auth_handler.py

  💡 Use @filename or /path to reference files in your prompt

# 패턴 없이 실행하면 사용법 표시
▶ @?
  📁 File Search
  Usage: /files <pattern>  or  @?<pattern>
  Examples:
    /files auth       → find files with 'auth' in name
    @?test           → find test files
    /files *.py      → find all Python files
```

#### 2. 인터랙티브 파일 선택

`@pattern?` 입력 시 선택 가능한 파일 목록이 자동으로 표시됩니다:

```bash
▶ Review @main?

  📁 Select a file (or Esc to cancel):
    1. paper/main.tex
    2. src/main.py
    3. tests/main_test.py

  Enter number (1-3) or Esc: 1

  ✓ Selected: @paper/main.tex
  Continue editing (or press Enter to submit):
▶ Review @paper/main.tex and suggest improvements    # 계속 입력 가능!
```

**사용법:**
- `@pattern?` - 패턴과 일치하는 파일 선택 메뉴 표시
- `/path?` - 절대 경로로 파일 검색 및 선택
- 숫자 입력으로 파일 선택
- 선택 후 프롬프트 계속 편집 가능
- `Enter`로 최종 제출
- `Esc` 또는 빈 입력으로 취소

#### 3. Tab 자동완성

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

**💡 Tip:** Planning 중에 `Ctrl+C`로 언제든 취소 가능합니다.

```bash
⚙  Generating plan for: Build REST API
⠋  Planning...
^C
✖ Planning cancelled by user (Ctrl+C)
  Planning cancelled. Returning to prompt.

▶    # REPL로 돌아옴
```

### 에이전트 자동 배정

플래너는 태스크 유형에 따라 적합한 에이전트를 자동으로 배정합니다:

- **Claude**: 분석, 설계, 리뷰, 리팩토링, 문서화, 복잡한 디버깅
- **Codex**: 코드 생성, 보일러플레이트, 테스트, API 구현, 데이터 처리

모든 태스크가 한 에이전트로 배정되면 경고가 표시되며, 플랜 편집기에서 `r <n> <agent>` 명령어로 재배정할 수 있습니다.

```
⚠️  Warning: All 5 tasks assigned to CLAUDE.
   Consider reassigning some tasks in the plan editor.
   Use 'r <task_id> codex' or 'r <task_id> claude'
```

### ⚡ 자동 병렬 실행

**의존성이 없는 태스크는 자동으로 병렬 실행됩니다!**

플래너가 자동으로 독립적인 태스크를 감지하여 동시에 실행합니다:

```
  ⚡ 3 task(s) will run in parallel for faster execution

  #  Agent     Title
  ────────────────────────────────────────────────
  1  CLAUDE   Design API architecture
  2  CODEX    Generate test fixtures          ∥parallel
  3  CODEX    Setup database schema            ∥parallel
  4  CLAUDE   Review and integrate code
```

**병렬 실행 조건:**
- 서로 의존성이 없는 태스크
- 동일한 단계(wave)에서 실행 가능한 태스크
- 2개 이상의 태스크가 동시에 실행 가능할 때

**속도 향상 예시:**
- 순차 실행: Task2(5분) → Task3(5분) = **10분**
- 병렬 실행: Task2(5분) ∥ Task3(5분) = **5분** ⚡

### 실행 흐름

```
목표 입력
    │
    ▼
Claude가 서브태스크 분해 + 에이전트 배정
    │
    ▼
플랜 미리보기 (대화형 편집기)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✨ Review the plan above and choose an action:
  • Press Enter to execute now
  • Type h for all commands
  • Type r <n> <agent> to reassign a task
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

plan> (Enter to execute, h for help)
    │
    ├─ Enter       → 바로 실행
    ├─ h           → 전체 명령어 보기
    ├─ r 2 codex   → 태스크 2를 Codex로 변경
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

#### 🚀 Quick Actions
| 명령어 | 설명 | 예시 |
|--------|------|------|
| `Enter` | **즉시 실행** (추가 프롬프트 없이) | 그냥 Enter |
| `go` | 실행 (선택적으로 지시사항 추가 가능) | `go` |
| `h` \| `help` | 전체 도움말 보기 | `h` |
| `q` \| `quit` | 취소하고 종료 | `q` |

#### ✏️ 태스크 수정
| 명령어 | 설명 | 예시 |
|--------|------|------|
| `r <n> <agent>` | 태스크 n의 에이전트 변경 | `r 2 codex` |
| `e <n>` | 태스크 n의 프롬프트 편집 | `e 3` |
| `v <n>` | 태스크 n의 전체 프롬프트 보기 | `v 1` |
| `d <n>` | 태스크 n 삭제 | `d 5` |

#### ➕ 추가 설정
| 명령어 | 설명 | 예시 |
|--------|------|------|
| `a` | 새 태스크 추가 | `a` |
| `p <n>` | 태스크 n 병렬 실행 토글 | `p 2` |
| `dep <n> <ids>` | 의존성 설정 | `dep 3 1 2` |
| `note <text>` | 전역 지시사항 설정 | `note Use type hints` |
| `show` | 플랜 새로고침 | `show` |
| `verbose` | 상세 모드 토글 | `verbose` |

### 💡 Quick Start 예시

**시나리오 1: 플랜이 마음에 들어서 바로 실행**
```
plan> (Enter to execute, h for help) [Enter]
→ 즉시 실행! 추가 프롬프트 없음
```

**시나리오 2: 실행 전 간단한 지시사항 추가**
```
plan> (Enter to execute, h for help) go

  Optional: Add global instructions (Enter to skip):
  + Use async/await for all I/O operations
  ✓ Added: Use async/await for all I/O operations
→ 지시사항 포함해서 실행
```

**시나리오 3: 태스크 수정 후 즉시 실행**
```
plan> (Enter to execute, h for help) r 2 codex
✓ Task 2 → CODEX
plan> (Enter to execute, h for help) [Enter]
→ 즉시 실행
```

**시나리오 4: 복잡한 전역 지시사항 (멀티라인)**
```
plan> (Enter to execute, h for help) note Use type hints, async/await, and comprehensive error handling
✓ Global note set: Use type hints, async/await...
plan> (Enter to execute, h for help) [Enter]
→ 지시사항 포함해서 실행
```

**시나리오 4: 도움말이 필요할 때**
```
plan> (Enter to execute, h for help) h

━━━ Plan Editor Commands ━━━

  🚀 Quick Actions:
    Enter              → Execute the plan now
    ...
```

### 전역 지시사항 추가

플랜 검토 중 또는 실행 직전에 모든 태스크에 공통으로 적용할 지시사항을 추가할 수 있습니다.

**방법 1: `note` 명령어로 미리 설정**

```
plan> note Use TypeScript strict mode and include error handling
✓ Global note set: Use TypeScript strict mode and include error handling
```

**방법 2: 실행 시 입력**

`Enter` 또는 `go` 명령어로 실행 시 추가 지시사항 입력 프롬프트가 표시됩니다:

```
plan> go

Optional: Add global instructions for all tasks
  (Enter multiple lines, empty line to finish, 'cancel' to abort)
  + Make sure all code follows PEP 8 style guide
  + Include comprehensive error handling
  + Add type hints to all functions
  +
✓ Added: Make sure all code follows PEP 8 style guide Include comprehensive...
```

**여러 줄 입력 방법:**
- 각 줄을 입력하고 Enter
- 붙여넣기(Paste)로 여러 줄 한 번에 입력 가능
- 빈 줄 입력하면 완료
- `cancel` 입력하면 취소
- 입력 없이 빈 줄만 입력하면 건너뛰기

**적용 방식**

전역 지시사항은 모든 태스크의 프롬프트 앞부분에 다음과 같이 추가됩니다:

```
=== Global Instructions ===
Make sure all code follows PEP 8 style guide

--- Your task ---
[원래 태스크 프롬프트]
```

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

같은 태스크에 대해 두 에이전트의 결과를 비교하고, **비판자 에이전트**가 자동으로 검토합니다.

```bash
collab --parallel "OAuth2 로그인 플로우 구현"
collab --parallel "이 알고리즘의 시간복잡도를 줄이는 방법"
```

```
  ✓ [CLAUDE]  ...결과...
  ✓ [CODEX]   ...결과...

── Critic [CLAUDE] ──────────────────────────
  비판자 검토 결과: 어떤 응답이 더 신뢰할 수 있는지,
  누락된 부분은 무엇인지, 개선 방향은 무엇인지 분석
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
| `/files <pattern>` | 패턴과 일치하는 파일 찾기 |
| `@?<pattern>` | 파일 빠른 검색 (`/files`의 단축 명령어) |
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

## 비판자 에이전트

병렬로 에이전트를 실행할 때, 최소 한 개의 서브에이전트가 자동으로 **비판자(Critic)** 역할을 맡아 다른 에이전트의 출력을 검토합니다.

### 동작 위치

| 모드 | 비판자 실행 조건 |
|------|-----------------|
| `collab --parallel` | Claude + Codex 완료 후 항상 실행 |
| Research Step 2 (분석) | 분석가 ≥ 2명일 때 |
| Research Step 3 (구현) | 구현자 ≥ 2명일 때 |

### 비판자가 검토하는 항목

1. **Logical Flaws** — 잘못된 추론이나 틀린 가정
2. **Missing Considerations** — 놓친 중요 요소
3. **Contradictions** — 에이전트 간 의견 불일치 시 어느 쪽이 맞는지
4. **Overconfidence** — 근거 없이 과신하는 주장
5. **Verdict** — 어떤 출력을 따르고 어떻게 개선할지 권고

비판자 결과는 Research 모드에서 **합성(Synthesizer)** 단계 이전에 실행되어, 이후 단계가 비판을 반영한 종합 결론을 사용합니다.

---

## AI 연구 모드

AI 모델 개발을 위한 **6단계 연구 루프**를 N 라운드 반복합니다.
각 라운드의 결론이 다음 라운드의 컨텍스트로 자동 전달됩니다.

### 라운드 구조

```
┌──────────────────────────────────────────────────────────────────┐
│  Step 1  Goal Understanding       Claude  (1개)                  │
│          ↓                                                       │
│  Step 2  Problem Analysis         Claude × N  ── 병렬            │
│                                   + Critic → Synthesizer         │
│          ↓ (합성)                                                │
│  Step 3  Methodology + Impl.      Claude(설계) + Codex × N      │
│                                   + Critic (N≥2 시)  ── 병렬    │
│          ↓                                                       │
│  Step 4  Experiment Execution     Codex × N  ── 병렬             │
│          ↓                                                       │
│  Step 5  Result Analysis          Claude  (1개)                  │
│          ↓                                                       │
│  Step 6  Conclusion               Claude → 다음 Round 전달       │
└──────────────────────────────────────────────────────────────────┘
          ↓  next_hypotheses 자동 carry-over
          Round 2 → Round 3 → ...
```

### 기본 실행

```bash
# 3라운드 (기본값)
collab research "MVTec 이상 탐지에서 Pixel AP를 5% 향상시켜라"

# 라운드 수 지정
collab research --rounds 5 "Continual learning forgetting 문제 해결"

# Interactive 모드 (각 round 후 확인)
collab research --rounds 10 -i "복잡한 최적화 작업"
```

### 🎯 모델 자동 선택

각 태스크의 복잡도에 따라 적절한 모델이 **자동으로 선택**됩니다:

**Claude 모델:**
- ⚡ **Haiku**: 간단한 작업 (todo 리스트, 포맷팅)
- 🎯 **Sonnet**: 일반 개발 작업 (구현, 테스트, 리팩토링)
- 🧠 **Opus**: 복잡한 작업 (아키텍처, 분석, 최적화)

**Codex 모델:**
- ⚡⚡ **gpt-5.3-codex-spark**: 초고속 boilerplate
- ⚡ **gpt-5.1-codex-mini**: 기본 코딩 작업
- 🎯 **gpt-5.3-codex**: 최신 agentic coding (기본값)
- 🧠 **gpt-5.1-codex-max**: 복잡한 추론
- 🚀 **gpt-5.2**: 매우 복잡한 작업

모델 선택은 plan UI에서 확인 가능:
```
  #  Agent    Model          Title
  ───────────────────────────────────────────
  1  CLAUDE   ⚡ Haiku      Create plan
  2  CODEX    🎯 5.3        Implement API
  3  CLAUDE   🧠 Opus       Design architecture
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

### 🚀 Multi-GPU 병렬 실험 실행

**여러 GPU가 있을 경우 실험을 동시에 병렬로 실행**합니다.

**자동 GPU 할당:**
```
  🖥️  Available GPUs:
    GPU 0: NVIDIA RTX 4090         |  22.5GB free |  15% util
    GPU 1: NVIDIA RTX 4090         |  23.1GB free |   8% util
    GPU 2: NVIDIA RTX 3090         |  22.8GB free |  12% util

  🎯 GPU Allocation for Parallel Execution:
    Experiment 1 → GPU [0]
    Experiment 2 → GPU [1]
    Experiment 3 → GPU [2]

  🚀 Starting 3 experiments in parallel...
```

**동작 방식:**
1. **GPU 자동 감지** - nvidia-smi로 사용 가능한 GPU 확인
2. **지능형 할당** - 메모리 여유가 많고 사용률이 낮은 GPU 우선 선택
3. **병렬 실행** - 각 실험이 서로 다른 GPU에서 동시 실행
4. **자동 환경 설정** - CUDA_VISIBLE_DEVICES 자동 설정
5. **동시 모니터링** - 모든 실험의 진행 상황 동시 추적

**GPU 메모리 요구사항 반영:**
Interactive 모드에서 설정한 GPU 메모리 제한이 자동으로 반영됩니다:
```bash
collab research -i --experiments 4 "모델 최적화"

> GPU memory limit: 8GB  # 8GB 이상 여유가 있는 GPU만 사용
```

**성능 향상:**
- GPU 1개: 실험 3개 × 4시간 = **12시간**
- GPU 3개: 실험 3개 ∥ 병렬 = **4시간** ⚡ (3배 속도)

**자동 Fallback:**
- GPU 없으면: CPU로 순차 실행
- GPU 부족하면: 사용 가능한 GPU에 순환 할당
- 실험 수 > GPU 수: 라운드 로빈 방식으로 할당

### 📚 연구 메모리 시스템

Research 모드는 **자동으로 학습**하며, 이전 라운드의 실수와 인사이트를 기억합니다.

**자동 추출:**
- ❌ **실수/실패**: "mistake", "error", "failed" 등의 키워드 감지
- 💡 **인사이트/성공**: "insight", "discovered", "success" 등의 키워드 감지

**메모리 활용:**
```
Round 1: loss가 nan이 되는 문제 발견 → 메모리에 기록
Round 2: 이전 실수를 참고하여 gradient clipping 적용 → 성공
Round 3: 성공한 기법을 더 발전시켜 최적화
```

**저장 파일:**
- `research_learnings.md`: 모든 학습 내용이 마크다운으로 저장
- 각 Step의 프롬프트에 자동으로 메모리 컨텍스트 주입

### 📊 실험 로그 모니터링

Research Step 4 (실험 실행) 중 로그를 실시간으로 확인할 수 있습니다.

**명령어:**
```bash
# 로그 tail 보기 (최근 20줄)
collab log <log_file_path>

# 더 많은 줄 보기
collab log <log_file_path> --tail 50

# 전체 로그 보기
collab log <log_file_path> --full

# 필터링 없이 원본 보기
collab log <log_file_path> --no-filter
```

**자동 파싱 정보:**
- Epoch 진행률
- Loss 값
- 메트릭 (AUC, Pixel AP 등)
- 에러 및 경고

**실시간 업데이트:**
백그라운드 실험 중에는 60초마다 자동으로 로그 요약이 표시됩니다.

### ⏸️ Interactive 라운드 제어

`--interactive` (`-i`) 플래그로 각 라운드 후 진행 여부를 확인하고, 실험 전 제약 조건을 설정할 수 있습니다.

```bash
collab research --rounds 10 -i "복잡한 최적화 작업"
```

**Interactive 모드 기능:**

1. **실험 제약 조건 설정** (Step 3 전)
```
══════════════════════════════════════════════════════════════════
  📋 Experiment Configuration
══════════════════════════════════════════════════════════════════

  Please provide constraints for the experiments:
  (Press Enter to skip any question)

  🖥️  Hardware Constraints:
    GPU memory limit (e.g., '8GB', '16GB'): 8GB
    CPU memory limit (e.g., '32GB', '64GB'): 32GB
    Max batch size: 32

  🎯 Regularization & Training:
    Regularization methods (e.g., 'dropout, L2, early_stopping'): dropout, early_stopping
    Max training epochs: 100
    Learning rate range (e.g., '1e-4 to 1e-3'): 1e-4 to 1e-3

  🔬 Experiment Specifics:
    Any special requirements or constraints: use FP16
    Techniques to avoid (e.g., 'mixed precision, gradient accumulation'): gradient checkpointing
```

2. **라운드 진행 확인** (각 라운드 후)
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Round 1/10 completed.
  9 round(s) remaining.

  Continue to next round? [Y/n/q]:
```

**옵션:**
- `Enter` 또는 `y`: 다음 라운드 진행
- `n` 또는 `q`: 중단 (진행 상황은 자동 저장됨)
- `Ctrl+C`: 언제든 중단

**제약 조건 활용:**
- 모든 제약 조건은 실험 생성 시 자동으로 적용됨
- GPU 메모리 부족, OOM 에러 사전 방지
- 불필요한 기법 사용 회피
- 실험 설정의 일관성 보장

중단 후 `--resume`으로 이어서 진행 가능합니다 (제약 조건은 저장됨).

### 🔄 세션 재개 (Picker)

`--resume` 옵션으로 중단된 연구를 이어서 진행할 수 있습니다.

**인터랙티브 선택:**
```bash
# 경로 없이 실행하면 최근 세션 목록 표시
collab research --resume
```

출력 예시:
```
╔════════════════════════════════════════════════════════════════╗
║  Recent Research Sessions                                      ║
╚════════════════════════════════════════════════════════════════╝

  #    Updated           Progress      Goal
  ──────────────────────────────────────────────────────────────
  1    2024-01-15        Round 2/3     MVTec Pixel AP 5% 향상
  2    2024-01-14        Round 1/5     LoRA rank 최적화
  3    2024-01-13        Round 3/3     Continual learning

  💡 Tip: Enter number to resume, or 'q' to cancel

Select session: 1

  ✓ Resuming: MVTec Pixel AP 5% 향상
  📍 /path/to/research_state.json
  🔄 Progress: Round 2/3
```

**직접 지정:**
```bash
# 특정 research_state.json 파일 지정
collab research --resume /path/to/research_state.json
```

매 Step마다 `research_state.json`이 자동 저장되므로
중간에 중단되어도 이어서 진행할 수 있습니다.

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

### 장시간 실행 실험 (딥러닝 학습) 지원 🚀

Step 4 (Experiment Execution)에서 **몇 시간 ~ 며칠이 소요되는 딥러닝 학습**을 백그라운드로 실행하고 자동으로 모니터링합니다.

#### 동작 방식

1. **자동 감지**: Codex 에이전트가 `BACKGROUND_TASK: true` 태그를 출력하면 백그라운드 실행으로 전환
2. **백그라운드 실행**: 학습 스크립트를 백그라운드 프로세스로 시작
3. **실시간 모니터링**: 로그 파일을 주기적으로 파싱하여 진행상황 표시
4. **에러 감지 & 자동 복구** ⚡NEW: 에러 발생 시 자동으로 수정 후 재시도 (최대 3회)
5. **완료 감지**: 특정 패턴 또는 파일 생성으로 완료 자동 감지
6. **자동 재개**: 완료 후 Step 5 (Result Analysis)로 자동 진행

#### 🔧 자동 에러 복구 시스템

실험 중 에러가 발생하면 **자동으로 감지하고 수정**합니다:

**감지되는 에러 유형:**
- Python 에러 (TypeError, ValueError, AttributeError 등)
- CUDA/GPU 메모리 부족
- 파일 없음/권한 에러
- Import/Module 에러
- 프로세스 충돌 또는 강제 종료
- 로그 업데이트 중단 (10분 이상 정지 시)

**자동 복구 프로세스:**
1. 로그에서 에러를 실시간 감지 (첫 5분간 2초마다 체크)
2. 에러 로그 전체를 Codex에게 전달
3. Codex가 에러 원인 분석 및 수정된 코드 생성
4. 수정된 코드로 자동 재실행
5. 최대 3회까지 재시도

**실행 예시:**
```
  🎯 Detected long-running experiment: exp-V65_baseline
  🚀 Started background task

  ⚠️  Experiment failed (attempt 1/3)
  📋 Error: CUDA out of memory...
  🔧 Attempting automatic fix...
  🤖 Asking Codex to analyze and fix the error...
  ✓ Generated fix. Retrying experiment...

  🚀 Started background task (attempt 2)
  ⠋ Epoch 45/60 (75%) | Loss=0.0234 | AUC=98.47%
  ✅ Task completed (succeeded after 1 retry)
```

#### Codex 에이전트 출력 형식

실험 에이전트가 다음 형식으로 응답하면 백그라운드 실행이 활성화됩니다:

```
BACKGROUND_TASK: true
COMMAND: python run_moleflow.py --task_classes leather grid transistor --num_epochs 60 --experiment_name V65_exp1
LOG_FILE: logs/V65_exp1/training.log
COMPLETION_PATTERN: Training completed
ESTIMATED_TIME: 4-6 hours
```

#### 실시간 진행상황 표시

```
  🚀 Started background task: exp-V65_exp1
  📝 PID: 12345
  📄 Logs: /Volume/MoLeFlow/logs/V65_exp1/training.log

  ⠋ Epoch 15/60 (25%) | Loss=1.2345 | AUC=94.23% | PIXEL_AP=52.31% [1h 23m]
```

로그 파일에서 자동으로 파싱하는 정보:
- **Epoch 진행**: `Epoch 5/60` 패턴
- **Loss 값**: `Loss: 1.234` 패턴
- **메트릭**: `AUC=0.985`, `Pixel AP: 58.3%` 등
- **경과 시간**: 실시간 카운터

#### 완료 감지 패턴

다음 패턴 중 하나가 로그에 나타나면 자동으로 완료 처리:

**성공 패턴:**
- `Training completed`
- `Experiment finished`
- `All tasks complete`
- `Final results:`
- `✓ ... complete`

**실패 패턴:**
- `Error:`, `Exception:`
- `CUDA out of memory`
- `Traceback`

#### 완료 후 자동 분석

실험이 완료되면 Step 5 (Result Analysis) 에이전트가 자동으로 호출되어:
1. 로그 파일에서 최종 메트릭 추출
2. 이전 라운드 결과와 비교
3. 성능 개선/하락 원인 분석
4. 다음 라운드를 위한 가설 제시

#### 사용 예시

```bash
# 딥러닝 학습 포함된 연구 세션 시작
collab research --rounds 3 "MVTec Pixel AP 58% → 62% 달성"
```

**실제 동작:**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Round 1 of 3
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Step 4 → Experiment Execution (2 experiments)

  🎯 Detected long-running experiment: exp-V65_baseline
  ⏱️  Estimated time: 4-6 hours

  🚀 Started background task: exp-V65_baseline
  📝 PID: 12345
  📄 Logs: logs/V65_baseline/training.log

  ⠋ Epoch 45/60 (75%) | Loss=0.0234 | AUC=98.47% | PIXEL_AP=58.18% [3h 45m]

  ... (4시간 30분 경과) ...

  ✅ Task completed: exp-V65_baseline (4h 32m)
     • auc: 98.51%
     • pixel_ap: 58.62%

━━━ Step 5 (자동 진행) → Result Analysis ━━━

  ✓ [CLAUDE]  Analyzing results...
  ...
```

#### 타임아웃 설정

기본 타임아웃은 24시간입니다. 더 긴 실험의 경우 코드에서 조정 가능:

```python
# research/monitor.py
DEFAULT_PATTERNS = CompletionPattern(
    ...
    timeout_seconds=72 * 3600,  # 72시간
)
```

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

모든 모드에서 `--resume` 플래그를 사용하거나 `collab resume` 명령어로 세션을 재개할 수 있습니다.

**방법 1: 인터랙티브 선택**
```bash
# 세션 목록에서 선택
collab resume
# 또는
collab --resume

# Research 모드의 경우
collab research --resume
```

**방법 2: 세션 ID 직접 지정**
```bash
# 세션 ID 지정
collab resume <session-id>
# 또는
collab --resume <session-id>

# Research 모드의 경우
collab research --resume /path/to/research_state.json
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
  --resume [id]     세션 재개 (ID 생략 시 인터랙티브 선택)
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
  --resume [path]     세션 재개 (경로 생략 시 인터랙티브 선택)
  -i, --interactive   각 라운드 후 진행 여부 확인
  --plan-only         라운드 구조만 출력, 실행하지 않음
```

### `collab log` (실험 로그 확인)

```
collab log <log_file_path> [옵션]

옵션:
  --tail N        최근 N줄만 표시 (기본: 20)
  --full          전체 로그 표시
  --no-filter     필터링 없이 원본 표시
  --no-color      색상 없이 표시
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
│   ├── model_selector.py     # 태스크 복잡도 기반 모델 자동 선택
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
│       ├── parallel_pool.py  # 병렬 에이전트 풀 + 비판자(Critic) 로직
│       ├── state.py          # 라운드 간 상태 관리
│       ├── memory.py         # 연구 메모리 시스템 (실수/인사이트 추적)
│       ├── monitor.py        # 백그라운드 실험 모니터링
│       ├── check_log.py      # 로그 확인 유틸리티 (collab log)
│       └── display.py        # 터미널 출력 (신택스 하이라이팅 포함)
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
