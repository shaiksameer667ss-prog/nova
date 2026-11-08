import sys

from nova.config import get_settings
from nova.controller.loop import run_task


def main() -> int:
    if len(sys.argv) < 2:
        print('usage: python -m nova.cli "<task>"')
        return 2
    task = " ".join(sys.argv[1:])
    settings = get_settings()
    result = run_task(task, settings)
    print(f"agent_success: {result['agent_success']}")
    print(f"steps:         {result['steps']}")
    print(f"wall:          {result['wall_seconds']:.1f}s")
    print(f"summary:       {result['summary']}")
    print(f"run_id:        {result['run_id']}")
    print("note: agent_success is NOT verification. Use the harness to check results.")
    return 0


if __name__ == "__main__":
    sys.exit(main())