"""Model selector: assigns appropriate model based on task complexity."""
from __future__ import annotations


# Claude model definitions
MODEL_HAIKU = "haiku"      # Fast, lightweight for simple tasks
MODEL_SONNET = "sonnet"    # Balanced for most tasks
MODEL_OPUS = "opus"        # Most capable for complex tasks

# Codex (OpenAI) model definitions
CODEX_SPARK = "gpt-5.3-codex-spark"      # Ultra-fast for simple tasks
CODEX_MINI = "gpt-5.1-codex-mini"        # Cheaper, faster for basic tasks
CODEX_STANDARD = "gpt-5.3-codex"         # Latest frontier agentic coding (default)
CODEX_MAX = "gpt-5.1-codex-max"          # Deep and fast reasoning
CODEX_FRONTIER = "gpt-5.2"               # Latest frontier model


def select_model_for_task(task: dict) -> str:
    """
    Analyze task and return appropriate model based on agent and complexity.

    Claude models:
    - haiku:  Simple, mechanical tasks (todo lists, simple formatting, basic operations)
    - sonnet: Standard development tasks (implementation, testing, refactoring)
    - opus:   Complex tasks (architecture, deep analysis, complex reasoning)

    Codex models:
    - gpt-5.3-codex-spark:  Ultra-fast for simple boilerplate
    - gpt-5.1-codex-mini:   Cheaper, faster for basic tasks
    - gpt-5.3-codex:        Latest frontier agentic coding (standard)
    - gpt-5.1-codex-max:    Deep reasoning and complex tasks
    - gpt-5.2:              Frontier model for very complex scenarios
    """
    title = task.get("title", "").lower()
    prompt = task.get("prompt", "").lower()
    agent = task.get("agent", "claude")

    # Keywords indicating simple tasks
    simple_keywords = [
        "todo", "plan", "list", "format", "rename", "move",
        "copy", "delete", "simple", "basic", "quick", "boilerplate"
    ]

    # Keywords indicating complex tasks
    complex_keywords = [
        "architect", "design", "analyze", "research", "strategy",
        "complex", "optimize", "performance", "security", "refactor",
        "migrate", "integration", "system design", "trade-off",
        "algorithm", "debug", "diagnose"
    ]

    combined_text = f"{title} {prompt}"

    # Determine complexity
    is_complex = any(keyword in combined_text for keyword in complex_keywords)
    is_simple = any(keyword in combined_text for keyword in simple_keywords)

    # Check prompt length as secondary indicator
    prompt_words = len(prompt.split())
    if not is_simple and prompt_words < 15:
        is_simple = True
    if not is_complex and prompt_words > 100:
        is_complex = True

    # Select model based on agent
    if agent == "codex":
        # Very complex tasks - use frontier or max
        if is_complex and prompt_words > 150:
            return CODEX_FRONTIER
        elif is_complex:
            return CODEX_MAX
        # Very simple tasks - use spark for speed
        elif is_simple and prompt_words < 10:
            return CODEX_SPARK
        # Basic tasks - use mini
        elif is_simple:
            return CODEX_MINI
        # Standard tasks - use latest agentic coding model
        else:
            return CODEX_STANDARD
    else:  # claude
        if is_complex:
            return MODEL_OPUS
        elif is_simple:
            return MODEL_HAIKU
        else:
            return MODEL_SONNET


def get_model_emoji(model: str) -> str:
    """Return emoji representation for model."""
    return {
        # Claude models
        MODEL_HAIKU: "⚡",   # Fast
        MODEL_SONNET: "🎯",  # Balanced
        MODEL_OPUS: "🧠",    # Smart
        # Codex models
        CODEX_SPARK: "⚡⚡",         # Ultra-fast
        CODEX_MINI: "⚡",           # Fast
        CODEX_STANDARD: "🎯",       # Balanced
        CODEX_MAX: "🧠",            # Smart
        CODEX_FRONTIER: "🚀",       # Frontier
    }.get(model, "🤖")


def get_model_label(model: str) -> str:
    """Return display label for model."""
    return {
        # Claude models
        MODEL_HAIKU: "Haiku",
        MODEL_SONNET: "Sonnet",
        MODEL_OPUS: "Opus",
        # Codex models
        CODEX_SPARK: "spark",
        CODEX_MINI: "mini",
        CODEX_STANDARD: "5.3",
        CODEX_MAX: "max",
        CODEX_FRONTIER: "5.2",
    }.get(model, model)
