"""6-step research round execution."""
from __future__ import annotations

import sys
import threading
import time
from typing import TYPE_CHECKING

from agent_collab.research.state import AgentOutput, RoundResult, StepResult
from agent_collab.research.parallel_pool import ParallelPool, PoolTask

if TYPE_CHECKING:
    from agent_collab.agents import ClaudeAgent, CodexAgent

# Spinner
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_USE_COLOR = sys.stderr.isatty()


def _c(text: str, *styles: str) -> str:
    if not _USE_COLOR:
        return text
    codes = {
        "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
        "cyan": "\033[96m", "green": "\033[92m", "yellow": "\033[93m",
        "red": "\033[91m",
    }
    return "".join(codes.get(s, "") for s in styles) + text + codes["reset"]


def _run_with_spinner(agent, prompt: str, cwd: str, label: str):
    """Run a single agent with spinner display."""
    done = threading.Event()
    result = None
    error = None

    def _worker():
        nonlocal result, error
        try:
            result = agent.run(prompt, cwd=cwd)
        except Exception as e:
            error = e
        finally:
            done.set()

    def _spin():
        i = 0
        while not done.is_set():
            sys.stderr.write(f"\r  {SPINNER[i % len(SPINNER)]}  {label}...")
            sys.stderr.flush()
            time.sleep(0.12)
            i += 1
        sys.stderr.write("\r" + " " * 80 + "\r")
        sys.stderr.flush()

    worker = threading.Thread(target=_worker, daemon=True)
    spinner = threading.Thread(target=_spin, daemon=True)

    worker.start()
    if sys.stderr.isatty():
        spinner.start()

    try:
        while worker.is_alive():
            worker.join(timeout=0.1)
    except KeyboardInterrupt:
        sys.stderr.write("\r" + " " * 80 + "\r")
        sys.stderr.flush()
        print(_c("\n\n  ⚠️  Cancelled by user (Ctrl+C)", "yellow", "bold"))
        print(_c("  Research state has been saved. You can resume with:", "dim"))
        print(_c("    collab resume", "cyan"))
        print()
        raise

    done.set()
    if sys.stderr.isatty():
        spinner.join(timeout=0.5)

    if error:
        raise error

    return result

_S1_UNDERSTAND = """\
You are an AI research scientist starting a new research round.

RESEARCH GOAL: {goal}
PREVIOUS ROUNDS CONTEXT:
{round_context}

RESEARCH MEMORY (Learnings from previous rounds):
{memory_context}

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

RESEARCH MEMORY (Key learnings):
{memory_context}

Your analytical perspective: {perspective}

Perform deep problem analysis covering:
1. **Root Cause Analysis**: Why does the current approach fail or underperform?
2. **Technical Bottlenecks**: Specific architectural/algorithmic issues
3. **Related Work Insights**: What do similar papers/methods suggest?
4. **Failure Modes**: What will fail and why?
5. **Recommended Approach**: The single most promising methodology to try
6. **Implementation Notes**: Key technical details for implementation

Be specific, technical, and actionable.
"""

_S2_PERSPECTIVES = [
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

RESEARCH MEMORY (Avoid past mistakes, build on successes):
{memory_context}

Design a concrete experimental methodology:
1. **Proposed Approach**: Describe the solution in detail
2. **Implementation Plan**: Step-by-step what code changes are needed
3. **Experiment Configurations**: List 2-4 specific configs to try
4. **Evaluation Protocol**: How to measure success
5. **Expected Outcome**: What results do you expect?

Output a JSON block at the end:
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

Implement the required changes:
1. Identify which files need to be modified
2. Write the actual code changes
3. Create any new scripts needed
4. Ensure the code is runnable

Focus ONLY on: {impl_task}
Make minimal, targeted changes. Do not break existing functionality.
"""

_S4_EXPERIMENT = """\
You are an AI researcher running an experiment.

RESEARCH GOAL: {goal}
WORKING DIRECTORY: {cwd}

IMPLEMENTATION:
{step3_output}

EXPERIMENT TO RUN: {exp_name}
{exp_description}

CRITICAL: If this is a LONG-RUNNING experiment (e.g., deep learning training taking hours/days):
1. Run it as a BACKGROUND_TASK
2. Specify the exact shell command
3. Provide the log file path to monitor
4. Indicate completion pattern to detect when done

Format for background tasks:
```
BACKGROUND_TASK: true
COMMAND: python run_moleflow.py --task_classes leather grid --num_epochs 60 --experiment_name V65_exp1
LOG_FILE: logs/V65_exp1/training.log
COMPLETION_PATTERN: Training completed
ESTIMATED_TIME: 4-6 hours
```

For SHORT experiments (< 2 minutes), run directly and report:
```
EXPERIMENT: {exp_name}
STATUS: [SUCCESS/FAILED/PARTIAL]
METRICS:
  - metric_name: value (vs baseline: X, delta: +/-Y%)
OBSERVATIONS:
  - key observation
ERRORS/WARNINGS:
  - any issues
```
"""

_S5_RESULTS = """\
You are an AI research scientist analyzing experimental results.

RESEARCH GOAL: {goal}
ROUND: {round_num}

METHODOLOGY (Step 3):
{step3_output}

EXPERIMENT RESULTS (Step 4):
{step4_output}

PREVIOUS BEST METRICS:
{best_metrics}

Provide rigorous result analysis:
1. **Result Summary**: What were the key numbers?
2. **What Worked**: Improvements and why (mechanism)
3. **What Failed**: Failures and root cause hypothesis
4. **Unexpected Findings**: Surprising results
5. **Statistical Confidence**: Are improvements real or noise?
6. **Best Configuration**: Which config performed best and why?

Be quantitative. Include specific numbers.
"""

_S6_CONCLUSION = """\
You are an AI research lead writing the round conclusion.

RESEARCH GOAL: {goal}
ROUND: {round_num} of {total_rounds}

FULL ROUND SUMMARY:
{full_round_context}

Write the research round conclusion:
1. **Key Findings**: Top 3 most important discoveries
2. **Best Result**: Highest performing configuration with exact metrics
3. **Understanding Gained**: What we now know that we didn't before
4. **Next Round Hypotheses**: 2-4 specific, testable hypotheses for Round {next_round}
5. **Research Direction**: Continue / Pivot / Done

End with a JSON block:
```json
{{
  "best_metric": "MetricName=Value",
  "next_hypotheses": ["Hypothesis 1", "Hypothesis 2"],
  "direction": "continue|pivot|done",
  "critical_question": "..."
}}
```
"""


def step1_understand(state, current_round: RoundResult, claude, cwd: str) -> StepResult:
    t0 = time.time()
    res = _run_with_spinner(
        claude,
        _S1_UNDERSTAND.format(
            goal=state.goal, round_context=state.round_context(),
            round_num=current_round.round_num,
            memory_context=state.memory.get_full_context(),
        ),
        cwd,
        _c("[CLAUDE]", "cyan", "bold") + _c(" Understanding goal", "dim")
    )
    output = AgentOutput(agent="claude", role="understander",
                         output=res.output, duration_s=res.duration_s,
                         success=res.success, error=res.error)

    # Extract learnings from output
    state.memory.extract_learnings_from_output(
        res.output, current_round.round_num, "Goal Understanding"
    )

    return StepResult(step_id=1, step_name="Goal Understanding",
                      outputs=[output], synthesized=res.output,
                      duration_s=time.time() - t0)


def step2_analyze(state, current_round: RoundResult, pool: ParallelPool, n_analysts: int = 2) -> StepResult:
    t0 = time.time()
    step1_out = current_round.steps.get("understand", StepResult(1, "")).primary_output()
    memory_ctx = state.memory.get_full_context()
    tasks = [
        PoolTask(role=f"analyst-{i+1}", agent="claude",
                 prompt=_S2_ANALYZE.format(
                     goal=state.goal, round_num=current_round.round_num,
                     step1_output=step1_out, round_context=state.round_context(),
                     perspective=_S2_PERSPECTIVES[i % len(_S2_PERSPECTIVES)],
                     memory_context=memory_ctx,
                 ))
        for i in range(n_analysts)
    ]
    outputs = pool.run(tasks, criticize=(n_analysts > 1), synthesize=(n_analysts > 1))
    synthesized = next((o.output for o in reversed(outputs) if o.role == "synthesizer"), "")
    if not synthesized and outputs:
        synthesized = outputs[-1].output

    # Extract learnings from all outputs
    for output in outputs:
        state.memory.extract_learnings_from_output(
            output.output, current_round.round_num, "Problem Analysis"
        )

    return StepResult(step_id=2, step_name="Problem Analysis",
                      outputs=outputs, synthesized=synthesized,
                      duration_s=time.time() - t0)


def step3_methodology(state, current_round: RoundResult, claude, codex_pool: ParallelPool,
                      n_implementers: int = 2, cwd: str = ".") -> StepResult:
    t0 = time.time()
    step2_out = current_round.steps.get("analyze", StepResult(2, "")).primary_output()
    plan_res = _run_with_spinner(
        claude,
        _S3_PLAN.format(
            goal=state.goal, round_num=current_round.round_num, step2_output=step2_out,
            memory_context=state.memory.get_full_context(),
        ),
        cwd,
        _c("[CLAUDE]", "cyan", "bold") + _c(" Designing methodology", "dim")
    )
    plan_output = plan_res.output
    impl_tasks = [
        PoolTask(role=f"implementer-{i+1}", agent="codex",
                 prompt=_S3_IMPLEMENT.format(
                     goal=state.goal, cwd=cwd, step3_plan=plan_output,
                     impl_task=f"Implement experiment configuration #{i+1} from the plan",
                 ))
        for i in range(n_implementers)
    ]
    impl_outputs = codex_pool.run(impl_tasks, criticize=(n_implementers > 1), synthesize=False)
    all_outputs = [AgentOutput(agent="claude", role="planner", output=plan_output,
                               duration_s=plan_res.duration_s, success=plan_res.success),
                   *impl_outputs]
    combined = f"[PLAN]\n{plan_output}\n\n" + "\n\n".join(
        f"[IMPLEMENTATION-{i+1}]\n{o.output}" for i, o in enumerate(impl_outputs))

    # Extract learnings
    state.memory.extract_learnings_from_output(
        plan_output, current_round.round_num, "Methodology Planning"
    )
    for output in impl_outputs:
        state.memory.extract_learnings_from_output(
            output.output, current_round.round_num, "Implementation"
        )

    return StepResult(step_id=3, step_name="Methodology & Implementation",
                      outputs=all_outputs, synthesized=combined,
                      duration_s=time.time() - t0)


def step4_experiment(state, current_round: RoundResult, codex_pool: ParallelPool,
                     n_experiments: int = 2, cwd: str = ".", max_retries: int = 3) -> StepResult:
    import json, re, sys
    from pathlib import Path
    from agent_collab.research.monitor import run_background_task, parse_experiment_command, get_log_content, _c

    t0 = time.time()
    step3_out = current_round.steps.get("methodology", StepResult(3, "")).primary_output()
    exp_configs = []
    match = re.search(r'```json\s*(\{.*?"experiments".*?\})\s*```', step3_out, re.DOTALL)
    if match:
        try:
            exp_configs = json.loads(match.group(1)).get("experiments", [])[:n_experiments]
        except Exception:
            pass
    if not exp_configs:
        exp_configs = [{"name": f"experiment_{i+1}", "description": f"Experiment variant {i+1}"}
                       for i in range(n_experiments)]

    # First, get agent plans for each experiment
    tasks = [
        PoolTask(role=f"exp-{cfg.get('name', f'exp_{i+1}')}", agent="codex",
                 prompt=_S4_EXPERIMENT.format(
                     goal=state.goal, cwd=cwd, step3_output=step3_out,
                     exp_name=cfg.get("name", f"exp_{i+1}"),
                     exp_description=cfg.get("description", ""),
                 ))
        for i, cfg in enumerate(exp_configs)
    ]
    outputs = codex_pool.run(tasks, synthesize=False)

    # Check if any outputs indicate background tasks
    background_tasks = []
    final_outputs = []

    for output in outputs:
        bg_info = parse_experiment_command(output.output)
        if bg_info:
            # This is a background task - try with automatic error recovery
            print(_c(f"\n  🎯 Detected long-running experiment: {output.role}", "yellow", "bold"))
            if 'estimated_time' in bg_info:
                print(_c(f"  ⏱️  Estimated time: {bg_info['estimated_time']}", "dim"))
            print()

            task_id = output.role
            current_setup = output.output
            retry_count = 0
            progress = None

            # Retry loop with automatic error recovery
            while retry_count <= max_retries:
                # Run experiment
                progress = run_background_task(
                    task_id=f"{task_id}_attempt{retry_count+1}" if retry_count > 0 else task_id,
                    command=bg_info['command'],
                    cwd=cwd,
                    log_file=bg_info.get('log_file'),
                    patterns=bg_info.get('patterns'),
                    wait=True,
                )

                if progress.status == "completed":
                    # Success! Break out of retry loop
                    break

                # Failed - attempt recovery
                retry_count += 1
                if retry_count > max_retries:
                    print(_c(f"\n  ❌ Experiment failed after {max_retries} retry attempts", "red", "bold"))
                    break

                print(_c(f"\n  ⚠️  Experiment failed (attempt {retry_count}/{max_retries})", "yellow", "bold"))
                print(_c(f"  📋 Error: {progress.error_message[:200]}...", "red"))
                print(_c(f"  🔧 Attempting automatic fix...", "cyan"))

                # Get full log for error analysis
                log_content = ""
                if bg_info.get('log_file'):
                    log_path = Path(cwd) / bg_info['log_file']
                    log_content = get_log_content(log_path, max_lines=200)

                # Ask Codex to fix the error
                fix_prompt = f"""The experiment failed with the following error. Analyze the error and provide a fixed implementation.

ORIGINAL TASK:
{step3_out}

EXPERIMENT NAME: {bg_info.get('experiment_name', task_id)}

PREVIOUS IMPLEMENTATION:
{current_setup}

ERROR LOG:
{log_content if log_content else progress.error_message}

INSTRUCTIONS:
1. Analyze the root cause of the error
2. Provide a COMPLETE fixed implementation
3. Use the same output format (BACKGROUND_TASK: true, COMMAND:, LOG_FILE:, etc.)
4. Make sure to handle edge cases that caused the failure
5. If it's a code error, provide the corrected code files

Respond with the fixed experiment setup:"""

                print(_c(f"  🤖 Asking Codex to analyze and fix the error...", "cyan"))

                # Get fixed implementation from Codex
                from agent_collab.agents import CodexAgent
                fix_result = codex_pool.agents[0].run(fix_prompt, cwd=cwd)

                if not fix_result.success:
                    print(_c(f"  ❌ Could not generate fix. Stopping retry.", "red"))
                    break

                # Parse the new setup
                new_bg_info = parse_experiment_command(fix_result.output)
                if not new_bg_info:
                    print(_c(f"  ❌ Fix did not produce valid experiment setup. Stopping retry.", "red"))
                    break

                print(_c(f"  ✓ Generated fix. Retrying experiment...", "green"))

                # Update for next iteration
                bg_info = new_bg_info
                current_setup = fix_result.output

            # Create final result output
            if progress and progress.status == "completed":
                result_text = f"""EXPERIMENT: {task_id}
STATUS: SUCCESS (Background task completed)
ATTEMPTS: {retry_count + 1}
DURATION: {progress.last_update - progress.started_at:.0f}s

METRICS:"""
                if progress.current_metric:
                    for k, v in progress.current_metric.items():
                        if k == 'loss':
                            result_text += f"\n  - {k}: {v:.4f}"
                        else:
                            result_text += f"\n  - {k}: {v:.2%}"

                if progress.current_epoch and progress.total_epochs:
                    result_text += f"\n\nCOMPLETED: {progress.current_epoch}/{progress.total_epochs} epochs"

                if retry_count > 0:
                    result_text += f"\n\n⚠️  NOTE: Succeeded after {retry_count} auto-fix attempt(s)"

                result_text += f"\n\n--- Final Setup ---\n{current_setup}"

                final_outputs.append(AgentOutput(
                    agent=output.agent, role=output.role,
                    output=result_text,
                    duration_s=progress.last_update - progress.started_at,
                    success=True,
                ))
            else:
                # Failed even after retries
                error_text = f"""EXPERIMENT: {task_id}
STATUS: FAILED (after {retry_count + 1} attempts)
ERROR: {progress.error_message if progress else 'Unknown error'}
EXIT_CODE: {progress.exit_code if progress else 'N/A'}

--- Last Setup Attempted ---
{current_setup}"""
                final_outputs.append(AgentOutput(
                    agent=output.agent, role=output.role,
                    output=error_text,
                    duration_s=progress.last_update - progress.started_at if progress else 0,
                    success=False, error=progress.error_message if progress else "Failed",
                ))
        else:
            # Regular short experiment, use output as-is
            final_outputs.append(output)

    # Extract learnings from experiment outputs
    for output in final_outputs:
        state.memory.extract_learnings_from_output(
            output.output, current_round.round_num, "Experiment"
        )
        # Specifically check for failures
        if not output.success or "FAILED" in output.output.upper():
            state.memory.add_failure(
                current_round.round_num, "Experiment",
                f"Experiment {output.role} failed", output.output[:300]
            )

    return StepResult(step_id=4, step_name="Experiment Execution",
                      outputs=final_outputs,
                      synthesized="\n\n".join(o.output for o in final_outputs),
                      duration_s=time.time() - t0)


def step5_results(state, current_round: RoundResult, claude, cwd: str = ".") -> StepResult:
    t0 = time.time()
    step3_out = current_round.steps.get("methodology", StepResult(3, "")).primary_output()
    step4_out = current_round.steps.get("experiment",  StepResult(4, "")).primary_output()
    best_metrics = "\n".join(f"Round {r.round_num}: {r.best_metric}"
                             for r in state.rounds if r.best_metric) or "No previous metrics."
    res = _run_with_spinner(
        claude,
        _S5_RESULTS.format(
            goal=state.goal, round_num=current_round.round_num,
            step3_output=step3_out, step4_output=step4_out, best_metrics=best_metrics,
        ),
        cwd,
        _c("[CLAUDE]", "cyan", "bold") + _c(" Analyzing results", "dim")
    )
    output = AgentOutput(agent="claude", role="result-analyst",
                         output=res.output, duration_s=res.duration_s, success=res.success)

    # Extract learnings - results often contain key insights
    state.memory.extract_learnings_from_output(
        res.output, current_round.round_num, "Result Analysis"
    )

    return StepResult(step_id=5, step_name="Result Analysis",
                      outputs=[output], synthesized=res.output,
                      duration_s=time.time() - t0)


def step6_conclusion(state, current_round: RoundResult, total_rounds: int,
                     claude, cwd: str = ".") -> StepResult:
    import json, re
    t0 = time.time()
    full_ctx = state.step_context(current_round, up_to_step=6)
    res = _run_with_spinner(
        claude,
        _S6_CONCLUSION.format(
            goal=state.goal, round_num=current_round.round_num,
            total_rounds=total_rounds, full_round_context=full_ctx,
            next_round=current_round.round_num + 1,
        ),
        cwd,
        _c("[CLAUDE]", "cyan", "bold") + _c(" Writing conclusion", "dim")
    )
    match = re.search(r'```json\s*(\{.*?\})\s*```', res.output, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(1))
            current_round.conclusion = res.output
            current_round.next_hypotheses = parsed.get("next_hypotheses", [])
            current_round.best_metric = parsed.get("best_metric")
        except Exception:
            current_round.conclusion = res.output
    else:
        current_round.conclusion = res.output

    output = AgentOutput(agent="claude", role="concluder",
                         output=res.output, duration_s=res.duration_s, success=res.success)

    # Extract learnings from conclusion
    state.memory.extract_learnings_from_output(
        res.output, current_round.round_num, "Conclusion"
    )

    return StepResult(step_id=6, step_name="Conclusion",
                      outputs=[output], synthesized=res.output,
                      duration_s=time.time() - t0)
