"""Experiment report generation for research sessions."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agent_collab.research.state import AgentOutput
    from agent_collab.agents import ClaudeAgent


def create_session_folder(session_id: str) -> Path:
    """Create folder structure for a research session."""
    from agent_collab.session_store import SESSION_ROOT

    session_dir = SESSION_ROOT / session_id / "experiments"
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def generate_experiment_report(
    experiment_output: 'AgentOutput',
    round_num: int,
    session_dir: Path,
    claude: 'ClaudeAgent',
    cwd: str
) -> Path:
    """
    Generate a detailed report for a single experiment.

    Returns the path to the generated report.
    """
    import re

    # Extract experiment name from role
    exp_name = experiment_output.role.replace('exp-', '')

    # Create filename with timestamp
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    report_file = session_dir / f"round{round_num}_{exp_name}_{timestamp}.md"

    # Extract key information from output
    output_text = experiment_output.output

    # Parse experiment details
    exp_summary = _extract_experiment_info(output_text)

    # Ask Claude to analyze the results
    analysis_prompt = f"""Analyze this experiment result and provide insights.

EXPERIMENT OUTPUT:
{output_text}

Provide a detailed analysis covering:
1. **Experiment Summary**: What was tested and why
2. **Key Findings**: Main results and metrics
3. **Performance Analysis**: How well did it perform? Compare to expectations
4. **Success/Failure Assessment**: Did it achieve the goal? Why or why not?
5. **Insights**: What did we learn? Any surprising discoveries?
6. **Recommendations**: Next steps or improvements to try

Be specific and quantitative. Focus on actionable insights.
"""

    analysis_result = claude.run(analysis_prompt, cwd=cwd)
    analysis = analysis_result.output if analysis_result.success else "Analysis failed - see raw output below"

    # Generate report content
    report_content = f"""# Experiment Report: {exp_name}

**Round**: {round_num}
**Timestamp**: {time.strftime('%Y-%m-%d %H:%M:%S')}
**Status**: {'✅ Success' if experiment_output.success else '❌ Failed'}
**Duration**: {experiment_output.duration_s:.1f}s ({_format_duration(experiment_output.duration_s)})

---

## 📋 Experiment Configuration

{exp_summary['config']}

---

## 🎯 Experiment Purpose

{exp_summary['purpose']}

---

## 📊 Results

{exp_summary['results']}

---

## 🔍 Detailed Analysis

{analysis}

---

## 📝 Raw Output

<details>
<summary>Click to expand full experiment output</summary>

```
{output_text}
```

</details>

---

**Report generated**: {time.strftime('%Y-%m-%d %H:%M:%S')}
**Experiment ID**: {experiment_output.role}
**Agent**: {experiment_output.agent.upper()}
"""

    # Write report
    report_file.write_text(report_content)

    return report_file


def _extract_experiment_info(output_text: str) -> dict:
    """Extract experiment information from output."""
    import re

    info = {
        'config': 'Configuration details not found',
        'purpose': 'Purpose not specified',
        'results': 'No results available'
    }

    # Extract configuration
    config_lines = []

    # Look for command
    cmd_match = re.search(r'COMMAND:\s*(.+)', output_text, re.IGNORECASE)
    if cmd_match:
        config_lines.append(f"**Command**: `{cmd_match.group(1).strip()}`")

    # Look for GPU info
    gpu_match = re.search(r'GPU:\s*(.+)', output_text, re.IGNORECASE)
    if gpu_match:
        config_lines.append(f"**GPU**: {gpu_match.group(1).strip()}")

    # Look for parameters
    param_patterns = [
        r'batch[_\s]?size[:\s=]+(\d+)',
        r'learning[_\s]?rate[:\s=]+([\d.e-]+)',
        r'epochs?[:\s=]+(\d+)',
        r'dropout[:\s=]+([\d.]+)',
    ]

    for pattern in param_patterns:
        matches = re.findall(pattern, output_text, re.IGNORECASE)
        if matches:
            param_name = pattern.split('[')[0].replace('\\', '')
            config_lines.append(f"**{param_name.title()}**: {matches[0]}")

    if config_lines:
        info['config'] = '\n'.join(config_lines)

    # Extract purpose/summary
    summary_match = re.search(r'Summary:\s*(.+?)(?:\n|$)', output_text, re.IGNORECASE)
    if summary_match:
        info['purpose'] = summary_match.group(1).strip()
    else:
        # Try to extract from experiment description
        desc_match = re.search(r'EXPERIMENT:\s*(.+?)(?:\n|STATUS)', output_text, re.IGNORECASE | re.DOTALL)
        if desc_match:
            info['purpose'] = desc_match.group(1).strip()

    # Extract results/metrics
    metrics_section = []

    # Look for METRICS section
    metrics_match = re.search(r'METRICS:(.+?)(?:\n\n|---|\Z)', output_text, re.DOTALL | re.IGNORECASE)
    if metrics_match:
        metrics_section.append(metrics_match.group(1).strip())

    # Look for individual metrics
    metric_patterns = [
        (r'(?:loss|Loss)[:\s]+([\d.]+)', 'Loss'),
        (r'(?:auc|AUC)[:\s=]+([\d.]+)', 'AUC'),
        (r'pixel[_\s]?ap[:\s]+([\d.]+)', 'Pixel AP'),
        (r'accuracy[:\s]+([\d.]+)', 'Accuracy'),
        (r'f1[:\s]+([\d.]+)', 'F1 Score'),
    ]

    found_metrics = []
    for pattern, name in metric_patterns:
        matches = re.findall(pattern, output_text, re.IGNORECASE)
        if matches:
            value = float(matches[-1])  # Take last occurrence
            if name == 'Loss':
                found_metrics.append(f"- **{name}**: {value:.4f}")
            else:
                # Convert to percentage if needed
                if value <= 1.0:
                    found_metrics.append(f"- **{name}**: {value:.2%}")
                else:
                    found_metrics.append(f"- **{name}**: {value:.2f}%")

    if found_metrics:
        metrics_section.append('\n'.join(found_metrics))

    # Look for status
    status_match = re.search(r'STATUS:\s*(.+)', output_text, re.IGNORECASE)
    if status_match:
        metrics_section.insert(0, f"**Status**: {status_match.group(1).strip()}")

    # Look for duration/epochs completed
    completed_match = re.search(r'COMPLETED:\s*(.+)', output_text, re.IGNORECASE)
    if completed_match:
        metrics_section.append(f"**Completed**: {completed_match.group(1).strip()}")

    if metrics_section:
        info['results'] = '\n\n'.join(metrics_section)

    return info


def _format_duration(seconds: float) -> str:
    """Format duration in human-readable form."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        hours = int(seconds / 3600)
        mins = int((seconds % 3600) / 60)
        return f"{hours}h {mins}m"


def generate_round_summary_report(
    round_num: int,
    all_experiments: list['AgentOutput'],
    session_dir: Path,
    claude: 'ClaudeAgent',
    cwd: str
) -> Path:
    """Generate a summary report for all experiments in a round."""

    timestamp = time.strftime('%Y%m%d_%H%M%S')
    summary_file = session_dir / f"round{round_num}_summary_{timestamp}.md"

    # Prepare experiment summaries
    exp_summaries = []
    for i, exp in enumerate(all_experiments, 1):
        status = "✅ Success" if exp.success else "❌ Failed"
        exp_summaries.append(f"""
### Experiment {i}: {exp.role}

**Status**: {status}
**Duration**: {_format_duration(exp.duration_s)}

{exp.output[:500]}...
""")

    all_outputs = "\n\n---\n\n".join(exp.output for exp in all_experiments)

    # Ask Claude for comparative analysis
    comparison_prompt = f"""Analyze and compare these {len(all_experiments)} experiments from Round {round_num}.

EXPERIMENTS:
{all_outputs}

Provide a comprehensive comparison covering:
1. **Overview**: What experiments were run and why
2. **Performance Comparison**: Which experiment performed best? Rank them.
3. **Key Differences**: What made the best one succeed?
4. **Insights**: What patterns or trends emerged?
5. **Recommendations**: Based on these results, what should we try next?

Be quantitative and specific. Provide actionable recommendations.
"""

    comparison_result = claude.run(comparison_prompt, cwd=cwd)
    comparison = comparison_result.output if comparison_result.success else "Comparison analysis failed"

    # Generate summary content
    summary_content = f"""# Round {round_num} Summary Report

**Generated**: {time.strftime('%Y-%m-%d %H:%M:%S')}
**Total Experiments**: {len(all_experiments)}
**Successful**: {sum(1 for e in all_experiments if e.success)}
**Failed**: {sum(1 for e in all_experiments if not e.success)}

---

## 📊 Experiments Overview

{''.join(exp_summaries)}

---

## 🔍 Comparative Analysis

{comparison}

---

## 📁 Individual Reports

Individual detailed reports for each experiment:

{chr(10).join(f'- [Experiment {i}: {exp.role}](round{round_num}_{exp.role.replace("exp-", "")}_*.md)' for i, exp in enumerate(all_experiments, 1))}

---

**Report generated**: {time.strftime('%Y-%m-%d %H:%M:%S')}
"""

    summary_file.write_text(summary_content)

    return summary_file


def generate_session_index(session_dir: Path, session_goal: str, total_rounds: int) -> Path:
    """Generate an index/README for the session with links to all reports."""

    index_file = session_dir / "README.md"

    # Find all report files
    round_summaries = sorted(session_dir.glob("round*_summary_*.md"))
    individual_reports = sorted(session_dir.glob("round*_exp-*.md"))

    # Group by round
    rounds_data = {}
    for report in individual_reports:
        # Extract round number from filename
        import re
        match = re.search(r'round(\d+)', report.name)
        if match:
            round_num = int(match.group(1))
            if round_num not in rounds_data:
                rounds_data[round_num] = []
            rounds_data[round_num].append(report)

    # Build content
    content = f"""# Research Session Reports

**Goal**: {session_goal}
**Total Rounds**: {total_rounds}
**Generated**: {time.strftime('%Y-%m-%d %H:%M:%S')}

---

## 📚 Round Summaries

"""

    for summary in round_summaries:
        round_match = re.search(r'round(\d+)', summary.name)
        if round_match:
            round_num = round_match.group(1)
            content += f"- [Round {round_num} Summary]({summary.name})\n"

    content += "\n---\n\n## 🔬 Individual Experiment Reports\n\n"

    for round_num in sorted(rounds_data.keys()):
        content += f"\n### Round {round_num}\n\n"
        for report in rounds_data[round_num]:
            exp_name = report.stem.split('_', 1)[1] if '_' in report.stem else report.stem
            content += f"- [{exp_name}]({report.name})\n"

    content += f"""

---

## 📖 How to Use These Reports

- **Start with Round Summaries**: Get a high-level overview of each round's experiments
- **Dive into Individual Reports**: See detailed analysis of specific experiments
- **Compare Across Rounds**: Track progress and learnings over time

Each report contains:
- ✅ Experiment configuration and parameters
- 🎯 Purpose and objectives
- 📊 Results and metrics
- 🔍 Detailed AI analysis and insights
- 💡 Recommendations for next steps

---

**Session folder**: `{session_dir}`
"""

    index_file.write_text(content)

    return index_file
