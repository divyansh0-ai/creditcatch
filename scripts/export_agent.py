"""Save the CreditCatch agent you built in TrueForge into the repo, and check its approval gates.

    python scripts/export_agent.py
    python scripts/export_agent.py --agent creditcatch --out agent/creditcatch.agent.json

Reads the saved agent from a running TrueForge (Build Agent -> Save Agent) and
writes its manifest (model, instructions, skills, MCP servers, sandbox) to
agent/creditcatch.agent.json, so the exact setup is versioned next to the code.
It also reports whether send_vendor_email and save_itc_register pause for
approval, and refuses to write the file if the manifest looks like it holds a
secret. MCP auth headers and model keys are not part of a TrueForge agent
manifest, but check the file before you commit it.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from watch_inbox import TrueForge  # noqa: E402

GATED = ("send_vendor_email", "save_itc_register")
# Both tools are annotated destructiveHint=True in server/app.py, so these tags cover them.
COVERS_WRITE_TOOLS = {"@all", "@write", "@destructive"}
DEFAULT_APPROVAL = ["@destructive"]  # TrueForge's default when require_approval_for_tools is omitted
SECRETISH = re.compile(r"key|secret|token|password|authorization|bearer", re.I)


def secrets_in(obj, path="") -> list[str]:
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and v.strip() and SECRETISH.search(k):
                found.append(f"{path}.{k}")
            found += secrets_in(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found += secrets_in(v, f"{path}[{i}]")
    return found


def approval_report(manifest: dict) -> tuple[list[str], bool]:
    lines, ok = [], True
    servers = manifest.get("mcp_servers") or []
    if not servers:
        return ["No MCP server is attached to this agent, so it can't reach the inbox or send anything."], False
    for tool in GATED:
        how = []
        for s in servers:
            rules = s.get("require_approval_for_tools") or DEFAULT_APPROVAL
            hit = [r for r in rules if r == tool or r in COVERS_WRITE_TOOLS]
            if hit:
                how.append(f"{s.get('name')}: {', '.join(hit)}")
        if how:
            lines.append(f"  {tool}: pauses for approval ({'; '.join(how)})")
        else:
            ok = False
            lines.append(f"  {tool}: NOT gated. Add it (or @destructive) to require_approval_for_tools.")
    return lines, ok


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agent", default="creditcatch", help="saved TrueForge agent name (default: creditcatch)")
    ap.add_argument("--trueforge", default="http://localhost:8790", help="TrueForge URL")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "agent" / "creditcatch.agent.json"))
    args = ap.parse_args(argv)

    tf = TrueForge(args.trueforge)
    try:
        name = tf.resolve_agent(args.agent)
        agents = tf._call("GET", "/api/v1/agents?limit=100").get("data", [])
    except RuntimeError as e:
        sys.exit(f"Can't export: {e}")
    manifest = next(a.get("manifest") for a in agents if a.get("name") == name)

    leaks = secrets_in(manifest)
    if leaks:
        sys.exit("Not writing it: these fields look like secrets: " + ", ".join(leaks))
    lines, gated = approval_report(manifest)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved agent '{name}' to {out}")
    print("Approval gates:")
    print("\n".join(lines))
    if not gated:
        print("Fix the approvals in Build Agent, save the agent, and run this again.")
        return 1
    rel = Path(os.path.relpath(out)).as_posix()
    print(f"Check the file, then commit it: git add {rel} && git commit -m \"Add our TrueForge agent setup\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
