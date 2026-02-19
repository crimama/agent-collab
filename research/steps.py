"""
6-step research round execution.
Each step function takes state + config and returns a StepResult.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from state import AgentOutput, RoundResult, StepResult
from parallel_pool import ParallelPool, PoolTask

if TYPE_CHECKING:
    from agents import ClaudeAgent, CodexAgent

# ─── Prompt templates ──────────────────────────────────────────────────────────

_S1_UNDERSTAND = """\
You are an AI research scientist starting a new research round.

RESEARCH GOAL: {goal}

PREVIOUS ROUNDS CONTEXT:
{round_context}

--- TASK ---
This is Round {round_num}. Perform a thorough Goal Understanding analysis.

Provide:
1. **Core Research Question**: What specific question does this round answer?
2. **Current State**: What is the baseline? What has already been tried?
3. **Success Metrics**: Specific, measurable targets (e.g., metric X > Y%)
4. **Hypotheses for This Round**: 2-3 concrete, testable hypotheses
5. **Key Challenges**: What makes this hard? What might go wrong?
6. **Scope**: What is in-scope vs out-of-scope for this round?

Be precise and scientific. Think like a top ML researcher.
"""

_S2_ANALYZE = """\
You are an AI research analyst performing deep problem analysis.

RESEARCH GOAL: {goal}
ROUND: {round_num}

GOAL UNDERSTANDING (Step 1):
{step1_output}

PREVIOUS ROUNDS:
{round_context}

--- TASK ---
Your analytical perspective: {perspective}

Perform deep problem analysis covering:
1. **Root Cause Analysis**: Why does the current approach fail or underperform?
2. **Technical Bottlenecks**: Specific architectural/algorithmic issues
3. **Related Work Insights**: What do similar papers/methods suggest?
4. **Failure Modes**: What will fail and why?
5. **Recommended Approach**: The single most promising methodology to try
6. **Implementation Notes**: Key technical details for implementation

Be specific, technical, and actionable. Cite concrete examples or mechanisms.
"""

_S2_ANALYZE_PERSPECTIVES = [
    "Focus on architectural/model design issues",
    "Focus on training dynamics, loss functions, and optimization",
    "Focus on data distribution, feature quality, and preprocessing",
]

_S3_PLAN = """\
You are an AI research planner. Design the experimental methodology.

RESEARCH GOAL: {goal}
ROUND: {round_num}

PROBLEM ANALYSIS:
{step2_output}

--- TASK ---
Design a concrete experimental methodology:
1. **Proposed Approach**: Describe the solution in detail
2. **Implementation Plan**: Step-by-step what code changes are needed
3. **Experiment Configurations**: List 2-4 specific configs to try
   (vary ONE thing at a time: lr, architecture, hyperparameter, etc.)
4. **Evaluation Protocol**: How to measure success
5. **Expected Outcome**: What results do you expect?
6. **Rollback Plan**: If this fails, what's the alternative?

Output a JSON block at the end with experiment configs:
```json
{{
  "experiments": [
    {{"name": "exp_1", "description": "...", "key_change": "...", "expected_gain": "..."}},
    {{"name": "exp_2", "description": "...", "key_change": "...", "expected_gain": "..."}}
  ]
}}
```
"""

_S3_IMPLEMENT = """\
You are an expert ML engineer implementing a research experiment.

RESEARCH GOAL: {goal}
WORKING DIRECTORY: {cwd}

METHODOLOGY PLAN:
{step3_plan}

YOUR SPECIFIC TASK: {impl_task}

--- TASK ---
Implement the required changes. Be precise and complete:
1. Identify which files need to be modified
2. Write the actual code changes
3. Create any new scripts needed
4. Ensure the code is runnable

Focus ONLY on: {impl_task}
Make minimal, targeted changes. Do not break existing functionality.
Output a runnable experiment script or clear code diff.
"""

_S4_EXPERIMENT = """\
You are an AI researcher running an experiment.

RESEARCH GOAL: {goal}
WORKING DIRECTORY: {cwd}

IMPLEMENTATION:
{step3_output}

EXPERIMENT TO RUN: {exp_name}
{exp_description}

--- TASK ---
Execute this experiment:
1. Verify the implementation is correct
2. Write and run the experiment script
3. Capture all output, logs, and metrics
4. Report results in a structured format:

```
EXPERIMENT: {exp_name}
STATUS: [SUCCESS/FAILED/PARTIAL]
METRICS:
  - metric_name: value (vs baseline: baseline_value, delta: +/-X%)
  ...
OBSERVATIONS:
  - key observation 1
  - key observation 2
ERRORS/WARNINGS:
  - any issues encountered
```

Run the experiment and report actual results.
"""

_S5_ANALYZE_RESULTS = """\
You are an AI research scientist analyzing experimental results.

RESEARCH GOAL: {goal}
ROUND: {round_num}

METHODOLOGY (Step 3):
{step3_output}

EXPERIMENT RESULTS (Step 4):
{step4_output}

PREVIOUS BEST METRICS:
{best_metrics}

--- TASK ---
Provide rigorous result analysis:
1. **Result Summary**: What were the key numbers?
2. **What Worked**: Improvements and why they worked (mechanism)
3. **What Failed**: Failures and root cause hypothesis
4. **Unexpected Findings**: Surprising results worth investigating
5. **Statistical Confidence**: Are improvements real or noise?
6. **Insight Extraction**: What does this tell us about the problem?
7. **Best Configuration**: Which config performed best and why?

Be quantitative. Include specific numbers. Think about causality, not just correlation.
"""

_S6_CONCLUSION = """\
You are an AI research lead writing the round conclusion.

RESEARCH GOAL: {goal}
ROUND: {round_num} of {total_rounds}

FULL ROUND SUMMARY:
{full_round_context}

--- TASK ---
Write the research round conclusion:

1. **Key Findings**: Top 3 most important discoveries
2. **Best Result**: Highest performing configuration with exact metrics
3. **Understanding Gained**: What we now know that we didn't before
4. **Next Round Hypotheses**: 2-4 specific, testable hypotheses for Round {next_round}
   (Must be concrete: "Try X because Y, expected gain: Z%")
5. **Research Direction**: Continue this path / Pivot / Near-done
6. **Critical Question**: The ONE question that would unlock the most progress

End with a JSON block:
```json
{{
  "best_metric": "MetricName=Value",
  "next_hypotheses": [
    "Hypothesis 1: ...",
    "Hypothesis 2: ...",
    "Hypothesis 3: ..."
  ],
  "direction": "continue|pivot|done",
  "critical_question": "..."
}}
```
"""


# ─── Step executors ────────────────────────────────────────────────────────────

def step1_understand(
    state,
    current_round: RoundResult,
    claude: "ClaudeAgent",
    cwd: str,
) -> StepResult:
    t0 = time.time()
    prompt = _S1_UNDERSTAND.format(
        goal=state.goal,
        round_context=state.round_context(),
        round_num=current_round.round_num,
    )
    res = claude.run(prompt, cwd=cwd)
    output = AgentOutput(agent="claude", role="understander",
                         output=res.output, duration_s=res.duration_s,
                         success=res.success, error=res.error)
    return StepResult(
        step_id=1, step_name="Goal Understanding",
        outputs=[output], synthesized=res.output,
        duration_s=time.time() - t0,
    )


def step2_analyze(
    state,
    current_round: RoundResult,
    pool: ParallelPool,
    n_analysts: int = 2,
) -> StepResult:
    t0 = time.time()
    step1_out = current_round.steps.get("understand", StepResult(1, "")).primary_output()

    perspectives = _S2_ANALYZE_PERSPECTIVES[:n_analysts]
    tasks = [
        PoolTask(
            role=f"analyst-{i+1}",
            agent="claude",
            prompt=_S2_ANALYZE.format(
                goal=state.goal,
                round_num=current_round.round_num,
                step1_output=step1_out,
                round_context=state.round_context(),
                perspective=p,
            ),
        )
        for i, p in enumerate(perspectives)
    ]

    synthesis_prompt = (
        f"Synthesize these {n_analysts} parallel analyses into one unified problem analysis. "
        f"Keep all unique insights. Resolve contradictions by noting both perspectives. "
        f"Output a clean, structured analysis document.\n\n"
        + "\n\n".join(f"=== ANALYST-{i+1} ===\n{t.prompt}" for i, t in enumerate(tasks))
    )

    outputs = pool.run(tasks, synthesize=(n_analysts > 1), synthesis_prompt=synthesis_prompt)
    synthesized = next((o.output for o in reversed(outputs) if o.role == "synthesizer"), "")
    if not synthesized and outputs:
        synthesized = outputs[-1].output

    return StepResult(
        step_id=2, step_name="Problem Analysis",
        outputs=outputs, synthesized=synthesized,
        duration_s=time.time() - t0,
    )


def step3_methodology(
    state,
    current_round: RoundResult,
    claude: "ClaudeAgent",
    codex_pool: ParallelPool,
    n_implementers: int = 2,
    cwd: str = ".",
) -> StepResult:
    t0 = time.time()
    step2_out = current_round.steps.get("analyze", StepResult(2, "")).primary_output()

    # 3a. Claude plans
    plan_res = claude.run(
        _S3_PLAN.format(
            goal=state.goal,
            round_num=current_round.round_num,
            step2_output=step2_out,
        ),
        cwd=cwd,
    )
    plan_output = plan_res.output

    # 3b. Codex implements (parallel)
    impl_tasks_desc = [
        f"Implement experiment configuration #{i+1} from the plan"
        for i in range(n_implementers)
    ]
    impl_tasks = [
        PoolTask(
            role=f"implementer-{i+1}",
            agent="codex",
            prompt=_S3_IMPLEMENT.format(
                goal=state.goal,
                cwd=cwd,
                step3_plan=plan_output,
                impl_task=desc,
            ),
        )
        for i, desc in enumerate(impl_tasks_desc)
    ]

    impl_outputs = codex_pool.run(impl_tasks, synthesize=False)

    all_outputs = [
        AgentOutput(agent="claude", role="planner",
                    output=plan_output, duration_s=plan_res.duration_s,
                    success=plan_res.success),
        *impl_outputs,
    ]

    combined = f"[PLAN]\n{plan_output}\n\n" + "\n\n".join(
        f"[IMPLEMENTATION-{i+1}]\n{o.output}" for i, o in enumerate(impl_outputs)
    )

    return StepResult(
        step_id=3, step_name="Methodology & Implementation",
        outputs=all_outputs, synthesized=combined,
        duration_s=time.time() - t0,
    )


def step4_experiment(
    state,
    current_round: RoundResult,
    codex_pool: ParallelPool,
    n_experiments: int = 2,
    cwd: str = ".",
) -> StepResult:
    import json, re
    t0 = time.time()
    step3_out = current_round.steps.get("methodology", StepResult(3, "")).primary_output()

    # Try to parse experiment configs from step3
    exp_configs = []
    match = re.search(r'```json\s*(\{.*?"experiments".*?\})\s*```', step3_out, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(1))
            exp_configs = parsed.get("experiments", [])[:n_experiments]
        except Exception:
            pass

    if not exp_configs:
        exp_configs = [
            {"name": f"experiment_{i+1}", "description": f"Experiment variant {i+1}", "key_change": ""}
            for i in range(n_experiments)
        ]

    tasks = [
        PoolTask(
            role=f"exp-{cfg.get('name', f'exp_{i+1}')}",
            agent="codex",
            prompt=_S4_EXPERIMENT.format(
                goal=state.goal,
                cwd=cwd,
                step3_output=step3_out,
                exp_name=cfg.get("name", f"exp_{i+1}"),
                exp_description=cfg.get("description", ""),
            ),
        )
        for i, cfg in enumerate(exp_configs)
    ]

    outputs = codex_pool.run(tasks, synthesize=False)

    return StepResult(
        step_id=4, step_name="Experiment Execution",
        outputs=outputs,
        synthesized="\n\n".join(o.output for o in outputs),
        duration_s=time.time() - t0,
    )


def step5_results(
    state,
    current_round: RoundResult,
    claude: "ClaudeAgent",
    cwd: str = ".",
) -> StepResult:
    t0 = time.time()
    step3_out = current_round.steps.get("methodology", StepResult(3, "")).primary_output()
    step4_out = current_round.steps.get("experiment", StepResult(4, "")).primary_output()

    best_metrics = "\n".join(
        f"Round {r.round_num}: {r.best_metric}" for r in state.rounds if r.best_metric
    ) or "No previous metrics recorded."

    res = claude.run(
        _S5_ANALYZE_RESULTS.format(
            goal=state.goal,
            round_num=current_round.round_num,
            step3_output=step3_out,
            step4_output=step4_out,
            best_metrics=best_metrics,
        ),
        cwd=cwd,
    )
    output = AgentOutput(agent="claude", role="result-analyst",
                         output=res.output, duration_s=res.duration_s,
                         success=res.success)
    return StepResult(
        step_id=5, step_name="Result Analysis",
        outputs=[output], synthesized=res.output,
        duration_s=time.time() - t0,
    )


def step6_conclusion(
    state,
    current_round: RoundResult,
    total_rounds: int,
    claude: "ClaudeAgent",
    cwd: str = ".",
) -> StepResult:
    import json, re
    t0 = time.time()

    # Build full round summary
    full_ctx = state.step_context(current_round, up_to_step=6)

    res = claude.run(
        _S6_CONCLUSION.format(
            goal=state.goal,
            round_num=current_round.round_num,
            total_rounds=total_rounds,
            full_round_context=full_ctx,
            next_round=current_round.round_num + 1,
        ),
        cwd=cwd,
    )

    # Parse JSON from conclusion
    next_hypotheses = []
    best_metric = None
    direction = "continue"

    match = re.search(r'```json\s*(\{.*?\})\s*```', res.output, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(1))
            next_hypotheses = parsed.get("next_hypotheses", [])
            best_metric = parsed.get("best_metric")
            direction = parsed.get("direction", "continue")
        except Exception:
            pass

    current_round.conclusion = res.output
    current_round.next_hypotheses = next_hypotheses
    current_round.best_metric = best_metric

    output = AgentOutput(agent="claude", role="concluder",
                         output=res.output, duration_s=res.duration_s,
                         success=res.success)
    return StepResult(
        step_id=6, step_name="Conclusion",
        outputs=[output], synthesized=res.output,
        duration_s=time.time() - t0,
    )
