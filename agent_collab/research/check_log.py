#!/usr/bin/env python3
"""Utility to check experiment logs - quick summary or full tail."""
import argparse
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_collab.research.monitor import show_log_tail, print_log_summary


def main():
    parser = argparse.ArgumentParser(
        description="Check experiment log files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show summary of current experiment
  python check_log.py logs/experiment_1/training.log

  # Show last 30 lines (filtered)
  python check_log.py logs/experiment_1/training.log --tail 30

  # Show last 50 lines (unfiltered)
  python check_log.py logs/experiment_1/training.log --tail 50 --no-filter

  # Show full log (all lines)
  python check_log.py logs/experiment_1/training.log --full
        """
    )

    parser.add_argument("log_file", help="Path to log file")
    parser.add_argument(
        "--tail", "-t", type=int, metavar="N",
        help="Show last N lines (default: show summary)"
    )
    parser.add_argument(
        "--full", "-f", action="store_true",
        help="Show full log (all lines)"
    )
    parser.add_argument(
        "--no-filter", action="store_true",
        help="Don't filter for important lines only"
    )
    parser.add_argument(
        "--no-color", action="store_true",
        help="Disable color output"
    )

    args = parser.parse_args()

    log_path = Path(args.log_file)

    if not log_path.exists():
        print(f"Error: Log file not found: {log_path}")
        sys.exit(1)

    # Determine what to show
    if args.full:
        # Show all lines
        try:
            with open(log_path, "r") as f:
                content = f.read()
            print(content)
        except Exception as e:
            print(f"Error reading log: {e}")
            sys.exit(1)

    elif args.tail:
        # Show tail
        show_log_tail(
            log_path,
            lines=args.tail,
            filter_important=not args.no_filter,
            colorize=not args.no_color
        )

    else:
        # Show summary (default)
        print_log_summary(log_path)
        print("\n💡 Tip: Use --tail N to see last N lines, or --full to see everything")


if __name__ == "__main__":
    main()
