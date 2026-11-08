"""Check the Nemotron setup end to end with your free build.nvidia.com key.

    $env:NVIDIA_API_KEY = "nvapi-..."
    .venv\\Scripts\\python scripts\\check_nemotron.py

1. a one-line ping to the model
2. the real tool-calling session agent on 20 s of simulated session data
3. AI triage of the demo caseload
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from neurogrip.agent import NEMOTRON_KWARGS, ToolBox, make_nvidia_client, nemotron_model, run_agent  # noqa: E402
from neurogrip.engine import Engine  # noqa: E402
from neurogrip.sources import MockSource  # noqa: E402
from neurogrip.store import MemoryStore  # noqa: E402
from neurogrip.triage import seed_demo_patients, triage_patients  # noqa: E402
from neurogrip.vision import MockVision  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles default to cp1252
    client = make_nvidia_client()
    if client is None:
        print("NVIDIA_API_KEY is not set. Get a free key with 'Generate API Key' on build.nvidia.com, then:\n"
              '  $env:NVIDIA_API_KEY = "nvapi-..."')
        return 1
    model = nemotron_model()
    print(f"model: {model}\n")

    print("1) ping")
    t = time.time()
    resp = client.chat.completions.create(model=model, max_tokens=200, **NEMOTRON_KWARGS,
                                          messages=[{"role": "user", "content": "Reply with exactly: NeuroGrip OK"}])
    print(f"   {resp.choices[0].message.content!r}  ({time.time() - t:.1f} s)\n")

    print("2) session agent (tool calls)")
    engine = Engine(MockSource(tremor_hz=4.5), MockVision(tremor_hz=4.5), MemoryStore())
    for _ in range(1000):  # 20 s of simulated session
        engine.step()
    t = time.time()
    out = run_agent(client, model, ToolBox(engine))
    for step in out["trace"]:
        print(f"   - {step['tool']}({json.dumps(step['args'])})")
    print(f"   summary: {out['summary']}")
    print(f"   plan:    {out['next_session_plan']}")
    print(f"   difficulty now {engine.state()['difficulty']}  ({time.time() - t:.1f} s)\n")

    print("3) triage")
    t = time.time()
    rows = triage_patients(client, model, seed_demo_patients())
    for r in rows[:5]:
        print(f"   {r['urgency']:<8} {r['name']:<12} {r.get('reason', '')}")
    print(f"   ({time.time() - t:.1f} s)")
    return 0 if out["trace"] else 2


if __name__ == "__main__":
    sys.exit(main())
