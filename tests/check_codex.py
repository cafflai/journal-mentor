"""Read-only Codex RPC check: config and skill discovery; never starts an AI turn."""
import argparse
import json
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--launcher", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    executable = shutil.which("codex.cmd") or shutil.which("codex")
    if not executable:
        raise SystemExit("Codex CLI not found")
    command = [executable, "app-server", "--stdio"]
    if args.launcher:
        for item in ("features.memories=false", "features.external_agent_memory_import=false",
                     "memories.generate_memories=false", "memories.use_memories=false"):
            command += ["-c", item]
    process = subprocess.Popen(command, cwd=root, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               encoding="utf-8", text=True)
    messages = queue.Queue()

    def read():
        for line in process.stdout:
            try:
                messages.put(json.loads(line))
            except ValueError:
                pass
        messages.put({"closed": True})

    threading.Thread(target=read, daemon=True).start()

    def request(identifier, method, params):
        process.stdin.write(json.dumps({"id": identifier, "method": method, "params": params}) + "\n")
        process.stdin.flush()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            response = messages.get(timeout=max(0.1, deadline - time.monotonic()))
            if response.get("closed"):
                raise RuntimeError("Codex app-server closed before response")
            if response.get("id") == identifier:
                if "error" in response:
                    raise RuntimeError("RPC failed for " + method + ": " + str(response["error"].get("code")))
                return response["result"]
        raise TimeoutError(method)

    try:
        request(1, "initialize", {"clientInfo": {"name": "journal-mentor-local-check", "version": "1.0"},
                                  "capabilities": {"experimentalApi": True}})
        process.stdin.write('{"method":"initialized","params":{}}\n')
        process.stdin.flush()
        config = request(2, "config/read", {"cwd": str(root), "includeLayers": False})["config"]
        skills = request(3, "skills/list", {"cwds": [str(root), str(root.parent)], "forceReload": True})
        # Never print global configuration, secrets, or unrelated skill metadata.
        output = {"launcher_overrides": args.launcher,
                  "features": {key: (config.get("features") or {}).get(key) for key in ("memories", "external_agent_memory_import")},
                  "memories": {key: (config.get("memories") or {}).get(key) for key in ("generate_memories", "use_memories")},
                  "skill_discovery": []}
        for item in skills.get("data", []):
            output["skill_discovery"].append({"cwd": item.get("cwd"),
                "journal_mentor": [{"name": s.get("name"), "path": s.get("path"), "enabled": s.get("enabled")}
                                   for s in item.get("skills", []) if s.get("name") == "journal-mentor"],
                "skill_error_count": len(item.get("errors", []))})
        if args.launcher and any(value is not False for section in ("features", "memories") for value in output[section].values()):
            raise RuntimeError("The four memory isolation overrides are not all effective")
        discovered = {item["cwd"]: item["journal_mentor"] for item in output["skill_discovery"]}
        local_skills = discovered.get(str(root), [])
        if len(local_skills) != 1 or local_skills[0].get("enabled") is not True:
            raise RuntimeError("The project skill was not discovered and enabled")
        if discovered.get(str(root.parent)):
            raise RuntimeError("The journal skill unexpectedly appears in the parent project")
        print(json.dumps(output, ensure_ascii=False, indent=2))
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    main()
