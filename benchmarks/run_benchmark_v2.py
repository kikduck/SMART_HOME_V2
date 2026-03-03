from __future__ import annotations

import argparse
import atexit
import json
import re
import subprocess
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


DEFAULT_MODEL = r"D:\PROG\TEST\SMART_HOME\gguf_models\Qwen3.5-4B-Q4_K_M.gguf"
DEFAULT_LLAMA_BIN = r"D:\PROG\TEST\SMART_HOME\llama-b8184-bin"
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CASES = BASE_DIR / "benchmarks" / "v2_cases.jsonl"
DEFAULT_PROMPT = BASE_DIR / "prompts" / "system_prompt_v2.txt"
DEFAULT_DECOMPOSER = BASE_DIR / "prompts" / "decomposer_prompt.txt"
DEFAULT_CONTRACTS = BASE_DIR / "schemas" / "tools_contracts.json"
DEFAULT_HOME_STATE = BASE_DIR / "knowledge" / "home_state.json"
DEFAULT_ALIASES = BASE_DIR / "knowledge" / "aliases.json"
DEFAULT_REPORT = BASE_DIR / "benchmarks" / "reports" / "benchmark_v2_report.json"


def _extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: List[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                chunks.append(str(item.get("text", "")))
            else:
                chunks.append(str(item))
        return "\n".join(chunks).strip()
    return str(content)


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _parse_json_payload(text: str) -> Optional[Any]:
    candidate = _strip_code_fences(text)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    for opening, closing in (("{", "}"), ("[", "]")):
        start = candidate.find(opening)
        end = candidate.rfind(closing)
        if start != -1 and end != -1 and end > start:
            snippet = candidate[start : end + 1]
            try:
                return json.loads(snippet)
            except json.JSONDecodeError:
                continue
    return None


def _normalize_device_args(tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize device -> devices for tool schemas that expect array."""
    if tool not in ("turn_on_devices", "turn_off_devices"):
        return args
    out = dict(args)
    if "device" in out and "devices" not in out:
        val = out.pop("device")
        out["devices"] = [val] if isinstance(val, str) else (val if isinstance(val, list) else [])
    return out


def _strip_null_args(args: Dict[str, Any]) -> Dict[str, Any]:
    """Remove keys with None/null values (treat as absent)."""
    return {k: v for k, v in args.items() if v is not None}


def _normalize_single_call(obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if "tool" in obj:
        args = obj.get("args", {})
        if not isinstance(args, dict):
            args = {}
        args = _normalize_device_args(str(obj["tool"]), args)
        args = _strip_null_args(args)
        return {"tool": str(obj["tool"]), "args": args}

    if "action" in obj:
        args = obj.get("args")
        if not isinstance(args, dict):
            args = {
                k: v
                for k, v in obj.items()
                if k
                not in {
                    "action",
                    "args",
                    "tool",
                    "details",
                    "message",
                    "status",
                    "result",
                    "response",
                }
                and v is not None
            }
        args = _normalize_device_args(str(obj["action"]), args)
        args = _strip_null_args(args)
        return {"tool": str(obj["action"]), "args": args}

    for key in ("actions", "commands", "tool_calls", "calls"):
        value = obj.get(key)
        if isinstance(value, list):
            normalized = [_normalize_single_call(x) for x in value if isinstance(x, dict)]
            normalized = [x for x in normalized if x is not None]
            if normalized:
                return {"tool": "multi", "args": {"_normalized_list": normalized}}
    return None


def normalize_calls(parsed: Any) -> Optional[List[Dict[str, Any]]]:
    if isinstance(parsed, dict):
        normalized = _normalize_single_call(parsed)
        if not normalized:
            return None
        if normalized["tool"] == "multi":
            return normalized["args"].get("_normalized_list", [])
        return [normalized]

    if isinstance(parsed, list):
        normalized_list: List[Dict[str, Any]] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            normalized = _normalize_single_call(item)
            if normalized:
                if normalized["tool"] == "multi":
                    normalized_list.extend(normalized["args"].get("_normalized_list", []))
                else:
                    normalized_list.append(normalized)
        return normalized_list or None
    return None


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_cases(path: Path) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at line {line_no}: {exc}") from exc
            payload.setdefault("id", f"case_{line_no}")
            payload.setdefault("category", "uncategorized")
            payload.setdefault("expected", [])
            cases.append(payload)
    return cases


def build_tools_block(contracts: Dict[str, Any]) -> str:
    lines: List[str] = []
    for tool in contracts.get("tools", []):
        name = tool["name"]
        required = ", ".join(tool.get("arguments", {}).get("required", []))
        optional = ", ".join(tool.get("arguments", {}).get("optional", []))
        signature = name + "("
        if required:
            signature += required
        if optional:
            if required:
                signature += ", "
            signature += optional + "?"
        signature += ")"
        lines.append(f"- {signature}: {tool.get('description', '').strip()}")
    return "\n".join(lines)


def build_knowledge_hint(home_state: Dict[str, Any]) -> str:
    rooms = sorted(home_state.get("rooms", {}).keys())
    fixtures: List[str] = []
    devices: List[str] = []
    for room_payload in home_state.get("rooms", {}).values():
        fixtures.extend(room_payload.get("lights", []))
        devices.extend(room_payload.get("devices", []))

    presets_payload = home_state.get("presets", {})
    lighting_presets = presets_payload.get("lighting", {})
    global_presets = presets_payload.get("global", {})

    if isinstance(lighting_presets, dict):
        lighting_list = sorted(lighting_presets.keys())
    else:
        lighting_list = sorted(lighting_presets)

    if isinstance(global_presets, dict):
        global_list = sorted(global_presets.keys())
    else:
        global_list = sorted(global_presets)

    sensors = home_state.get("sensor_types", {})
    if isinstance(sensors, dict):
        sensor_list = sorted(sensors.keys())
    else:
        sensor_list = sorted(sensors)

    return (
        f"rooms={rooms}\n"
        f"fixtures={sorted(set(fixtures))}\n"
        f"devices={sorted(set(devices))}\n"
        f"lighting_presets={lighting_list}\n"
        f"global_presets={global_list}\n"
        f"sensor_types={sensor_list}"
    )


def build_system_prompt(
    prompt_template_path: Path,
    tools_block: str,
    knowledge_hint: str,
) -> str:
    template = prompt_template_path.read_text(encoding="utf-8")
    prompt = template.replace("{{TOOLS_BLOCK}}", tools_block)
    prompt = prompt.replace("{{KNOWLEDGE_HINT}}", knowledge_hint)
    return prompt


def flatten_aliases(aliases_payload: Dict[str, Any]) -> Dict[str, str]:
    entries = aliases_payload.get("entries", {})
    out: Dict[str, str] = {}
    if isinstance(entries, dict):
        for alias, payload in entries.items():
            if isinstance(payload, dict):
                canonical = payload.get("canonical")
                if isinstance(canonical, str):
                    out[alias.lower()] = canonical.lower()
    return out


def build_known_sets(
    home_state: Dict[str, Any],
    aliases_payload: Dict[str, Any],
) -> Dict[str, set]:
    rooms = set(home_state.get("rooms", {}).keys())

    fixtures: set = set()
    devices: set = set()
    for room_payload in home_state.get("rooms", {}).values():
        fixtures.update(room_payload.get("lights", []))
        devices.update(room_payload.get("devices", []))

    presets_payload = home_state.get("presets", {})
    lighting_presets = presets_payload.get("lighting", {})
    global_presets = presets_payload.get("global", {})

    presets: set = set()
    if isinstance(lighting_presets, dict):
        presets.update(lighting_presets.keys())
    elif isinstance(lighting_presets, list):
        presets.update(lighting_presets)
    if isinstance(global_presets, dict):
        presets.update(global_presets.keys())
    elif isinstance(global_presets, list):
        presets.update(global_presets)

    sensors = home_state.get("sensor_types", {})
    sensor_types = set(sensors.keys()) if isinstance(sensors, dict) else set(sensors)

    aliases = flatten_aliases(aliases_payload)
    room_aliases = set()
    device_aliases = set()
    fixture_aliases = set()
    preset_aliases = set()

    entries = aliases_payload.get("entries", {})
    if isinstance(entries, dict):
        for alias, payload in entries.items():
            if not isinstance(payload, dict):
                continue
            alias_type = str(payload.get("type", "")).lower()
            if alias_type == "room":
                room_aliases.add(alias)
            elif alias_type == "device":
                device_aliases.add(alias)
            elif alias_type == "fixture":
                fixture_aliases.add(alias)
            elif alias_type == "preset":
                preset_aliases.add(alias)

    return {
        "rooms": {x.lower() for x in rooms}.union({x.lower() for x in room_aliases}),
        "fixtures": {x.lower() for x in fixtures}.union({x.lower() for x in fixture_aliases}),
        "devices": {x.lower() for x in devices}.union({x.lower() for x in device_aliases}),
        "presets": {x.lower() for x in presets}.union({x.lower() for x in preset_aliases}),
        "sensor_types": {x.lower() for x in sensor_types},
        "aliases": aliases,
    }


def _resolve_alias(value: str, aliases: Dict[str, str]) -> str:
    value_l = value.lower()
    return aliases.get(value_l, value_l)


def _value_matches(expected: Any, actual: Any) -> bool:
    if expected is True:
        return actual is not None
    if isinstance(expected, list):
        if isinstance(actual, list):
            expected_norm = [str(x).lower() for x in expected]
            actual_norm = [str(x).lower() for x in actual]
            return actual_norm == expected_norm
        return str(actual).lower() in [str(x).lower() for x in expected]
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.lower() == actual.lower()
    return expected == actual


def _args_exact(expected_args: Dict[str, Any], actual_args: Dict[str, Any]) -> bool:
    if set(expected_args.keys()) != set(actual_args.keys()):
        return False
    for key, expected_val in expected_args.items():
        if key not in actual_args:
            return False
        if not _value_matches(expected_val, actual_args[key]):
            return False
    return True


def _has_no_extra_args(expected_args: Dict[str, Any], actual_args: Dict[str, Any]) -> bool:
    return set(actual_args.keys()).issubset(set(expected_args.keys()))


def _is_known_entity(value: str, key: str, known: Dict[str, set], aliases: Dict[str, str]) -> bool:
    resolved = _resolve_alias(value, aliases)
    if key == "room":
        return resolved in known["rooms"]
    if key == "fixture":
        return resolved in known["fixtures"]
    if key == "device":
        return resolved in known["devices"]
    if key == "preset":
        return resolved in known["presets"]
    if key == "sensor_type":
        return resolved in known["sensor_types"]
    return True


def apply_entity_filter(
    parsed_calls: Optional[List[Dict[str, Any]]], known: Dict[str, set]
) -> Optional[List[Dict[str, Any]]]:
    """Safety: replace output with do_nothing if any entity is unknown (prevents wrong actions)."""
    if not parsed_calls or not isinstance(parsed_calls, list):
        return parsed_calls
    if _no_hallucination(parsed_calls, known):
        return parsed_calls
    return [{"tool": "do_nothing", "args": {"reason": "unknown_entity"}}]


def _no_hallucination(calls: List[Dict[str, Any]], known: Dict[str, set]) -> bool:
    aliases = known.get("aliases", {})
    for call in calls:
        args = call.get("args", {})
        for key, value in args.items():
            if key == "room" and isinstance(value, str):
                if not _is_known_entity(value, "room", known, aliases):
                    return False
            elif key == "rooms" and isinstance(value, list):
                for room_name in value:
                    if isinstance(room_name, str) and not _is_known_entity(
                        room_name, "room", known, aliases
                    ):
                        return False
            elif key == "fixture":
                if isinstance(value, str):
                    if not _is_known_entity(value, "fixture", known, aliases):
                        return False
                elif isinstance(value, list):
                    for fixture_name in value:
                        if isinstance(fixture_name, str) and not _is_known_entity(
                            fixture_name, "fixture", known, aliases
                        ):
                            return False
            elif key == "devices" and isinstance(value, list):
                for device_name in value:
                    if isinstance(device_name, str) and not _is_known_entity(
                        device_name, "device", known, aliases
                    ):
                        return False
            elif key == "preset" and isinstance(value, str):
                if not _is_known_entity(value, "preset", known, aliases):
                    return False
            elif key == "type" and isinstance(value, str):
                if not _is_known_entity(value, "sensor_type", known, aliases):
                    return False
    return True


def evaluate_case(
    case: Dict[str, Any],
    parsed_calls: Optional[List[Dict[str, Any]]],
    valid: bool,
    known: Dict[str, set],
    allowed_tools: set,
) -> Dict[str, Any]:
    expected_calls = case.get("expected", [])
    expected_tools = [c.get("tool") for c in expected_calls]

    if not valid or not parsed_calls:
        return {
            "tool_correct": False,
            "args_exact": False,
            "order_correct": False,
            "no_extra_args": False,
            "no_hallucination": False,
            "success": False,
        }

    actual_tools = [c.get("tool") for c in parsed_calls]

    tools_known = all(t in allowed_tools for t in actual_tools)
    tool_correct = Counter(actual_tools) == Counter(expected_tools) and len(actual_tools) == len(
        expected_tools
    )
    order_correct = actual_tools == expected_tools

    args_exact = True
    no_extra_args = True
    if len(parsed_calls) != len(expected_calls):
        args_exact = False
        no_extra_args = False
    else:
        for idx, expected in enumerate(expected_calls):
            expected_args = expected.get("args", {})
            actual_args = parsed_calls[idx].get("args", {})
            if not isinstance(actual_args, dict):
                args_exact = False
                no_extra_args = False
                continue
            if not _args_exact(expected_args, actual_args):
                args_exact = False
            if not _has_no_extra_args(expected_args, actual_args):
                no_extra_args = False

    no_hallucination = tools_known and _no_hallucination(parsed_calls, known)
    success = all([tool_correct, args_exact, order_correct, no_extra_args, no_hallucination])

    return {
        "tool_correct": tool_correct,
        "args_exact": args_exact,
        "order_correct": order_correct,
        "no_extra_args": no_extra_args,
        "no_hallucination": no_hallucination,
        "success": success,
    }


class LlamaServerProcess:
    def __init__(
        self,
        llama_bin_dir: Path,
        model_path: Path,
        host: str,
        port: int,
        n_ctx: int,
        n_gpu_layers: int,
        no_warmup: bool,
        log_dir: Path,
    ) -> None:
        self.llama_bin_dir = llama_bin_dir
        self.model_path = model_path
        self.host = host
        self.port = port
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers
        self.no_warmup = no_warmup
        self.log_dir = log_dir
        self.process: Optional[subprocess.Popen[str]] = None
        self.log_file = None
        self.log_path: Optional[Path] = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self, timeout_s: int = 240) -> None:
        server_exe = self.llama_bin_dir / "llama-server.exe"
        if not server_exe.exists():
            raise FileNotFoundError(f"llama-server not found: {server_exe}")

        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / f"qwen35_server_{int(time.time())}.log"
        self.log_file = self.log_path.open("w", encoding="utf-8")

        cmd = [
            str(server_exe),
            "-m",
            str(self.model_path),
            "--host",
            self.host,
            "--port",
            str(self.port),
            "-ngl",
            str(self.n_gpu_layers),
            "-c",
            str(self.n_ctx),
            "--jinja",
        ]
        if self.no_warmup:
            cmd.append("--no-warmup")

        self.process = subprocess.Popen(
            cmd,
            cwd=str(self.llama_bin_dir),
            stdout=self.log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
        atexit.register(self.stop)
        self._wait_ready(timeout_s=timeout_s)

    def _wait_ready(self, timeout_s: int) -> None:
        assert self.process is not None
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"llama-server ended early (code={self.process.returncode}). Logs: {self.log_path}"
                )
            for path in ("/health", "/v1/models"):
                try:
                    resp = requests.get(f"{self.base_url}{path}", timeout=2)
                    if resp.status_code == 200:
                        return
                except requests.RequestException:
                    pass
            time.sleep(1)
        raise TimeoutError(f"llama-server startup timeout ({timeout_s}s). Logs: {self.log_path}")

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log_file:
            self.log_file.close()
            self.log_file = None


class QwenParserClient:
    def __init__(
        self,
        base_url: str,
        model_path: str,
        temperature: float,
        top_p: float,
        max_tokens: int,
        timeout_s: int,
        id_slot: Optional[int] = None,
        cache_prompt_hint: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_path = model_path
        self.model_name = Path(model_path).stem
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self.id_slot = id_slot
        self.cache_prompt_hint = cache_prompt_hint

    def process(self, user_input: str, system_prompt: str, include_system: bool = True) -> Dict[str, Any]:
        messages: List[Dict[str, str]] = []
        if include_system:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_input})

        payload = {
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
        }
        if self.id_slot is not None:
            payload["id_slot"] = self.id_slot
        if self.cache_prompt_hint:
            payload["cache_prompt"] = True

        start = time.perf_counter()
        resp = requests.post(
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            timeout=self.timeout_s,
        )
        latency = (time.perf_counter() - start) * 1000
        if resp.status_code != 200:
            print(f"Error {resp.status_code}: {resp.text}")
        resp.raise_for_status()

        data = resp.json()
        content = _extract_text_content(data["choices"][0]["message"]["content"])
        parsed_raw = _parse_json_payload(content)
        parsed_calls = normalize_calls(parsed_raw)

        usage = data.get("usage", {})
        tokens = usage.get("completion_tokens", 0)
        if not isinstance(tokens, int):
            tokens = 0

        return {
            "response": content,
            "parsed_raw": parsed_raw,
            "calls": parsed_calls,
            "latency_ms": latency,
            "tokens": tokens,
        }

    def process_with_decompose(
        self, user_input: str, system_prompt: str, decomp_prompt: str, include_system: bool = True
    ) -> Dict[str, Any]:
        """Decompose multi-intent then parse each intent. Returns same format as process()."""
        payload_decomp = {
            "messages": [
                {"role": "system", "content": decomp_prompt},
                {"role": "user", "content": user_input},
            ],
            "temperature": 0.0,
            "top_p": self.top_p,
            "max_tokens": 64,
        }
        start_decomp = time.perf_counter()
        resp_decomp = requests.post(
            f"{self.base_url}/v1/chat/completions",
            json=payload_decomp,
            timeout=self.timeout_s,
        )
        resp_decomp.raise_for_status()
        content_decomp = _extract_text_content(
            resp_decomp.json()["choices"][0]["message"]["content"]
        )
        latency_decomp = (time.perf_counter() - start_decomp) * 1000
        decomp_parsed = _parse_json_payload(content_decomp)
        intents: List[str] = []
        if isinstance(decomp_parsed, dict):
            if decomp_parsed.get("type") == "multi" and isinstance(
                decomp_parsed.get("intents"), list
            ):
                intents = [str(s).strip() for s in decomp_parsed["intents"] if s]
            if not intents:
                intents = [decomp_parsed.get("intent", user_input) or user_input]
        if not intents:
            intents = [user_input]

        all_calls: List[Dict[str, Any]] = []
        total_latency = latency_decomp
        total_tokens = 0
        for intent in intents:
            r = self.process(intent, system_prompt, include_system=include_system)
            total_latency += r["latency_ms"]
            total_tokens += r["tokens"]
            if r["calls"]:
                all_calls.extend(r["calls"])

        return {
            "response": json.dumps(all_calls, ensure_ascii=False) if all_calls else "",
            "parsed_raw": all_calls,
            "calls": all_calls,
            "latency_ms": total_latency,
            "tokens": total_tokens,
        }


def aggregate(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(results)
    success = sum(1 for r in results if r["score"]["success"])
    rate = (100.0 * success / total) if total else 0.0

    metric_keys = [
        "tool_correct",
        "args_exact",
        "order_correct",
        "no_extra_args",
        "no_hallucination",
    ]
    metrics: Dict[str, float] = {}
    for key in metric_keys:
        metrics[key] = (100.0 * sum(1 for r in results if r["score"][key]) / total) if total else 0.0

    by_category: Dict[str, Any] = {}
    bucket = defaultdict(list)
    for item in results:
        bucket[item["category"]].append(item)

    for category, items in sorted(bucket.items()):
        cat_total = len(items)
        cat_success = sum(1 for x in items if x["score"]["success"])
        cat_metrics = {
            key: (100.0 * sum(1 for x in items if x["score"][key]) / cat_total)
            for key in metric_keys
        }
        by_category[category] = {
            "total": cat_total,
            "success": cat_success,
            "success_rate": round(100.0 * cat_success / cat_total, 2),
            "metrics": {k: round(v, 2) for k, v in cat_metrics.items()},
        }

    return {
        "total": total,
        "success": success,
        "success_rate": round(rate, 2),
        "metrics": {k: round(v, 2) for k, v in metrics.items()},
        "by_category": by_category,
    }


def print_console_summary(summary: Dict[str, Any]) -> None:
    print("\n" + "=" * 90)
    print("BENCHMARK V2 - PARSER SCORE")
    print("=" * 90)
    print(
        f"[GLOBAL] {summary['success']}/{summary['total']} "
        f"({summary['success_rate']:.1f}%)"
    )
    print(
        "[METRICS] "
        + " | ".join(f"{k}={v:.1f}%" for k, v in summary["metrics"].items())
    )
    print("\n[BY CATEGORY]")
    for category, payload in summary["by_category"].items():
        print(
            f"- {category:22} {payload['success']:2}/{payload['total']:2} "
            f"({payload['success_rate']:5.1f}%)"
        )
    print("=" * 90)


def main() -> None:
    parser = argparse.ArgumentParser(description="Smart Home V2 parser benchmark (llama-server)")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="GGUF model path")
    parser.add_argument("--llama-bin", type=str, default=DEFAULT_LLAMA_BIN, help="Directory with llama-server.exe")
    parser.add_argument("--cases", type=str, default=str(DEFAULT_CASES), help="JSONL benchmark cases")
    parser.add_argument("--prompt", type=str, default=str(DEFAULT_PROMPT), help="Prompt template file")
    parser.add_argument("--contracts", type=str, default=str(DEFAULT_CONTRACTS), help="Tools contract JSON")
    parser.add_argument("--home-state", type=str, default=str(DEFAULT_HOME_STATE), help="home_state.json")
    parser.add_argument("--aliases", type=str, default=str(DEFAULT_ALIASES), help="aliases.json")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="llama-server host")
    parser.add_argument("--port", type=int, default=8083, help="llama-server port")
    parser.add_argument("--n-ctx", type=int, default=4096, help="server context size")
    parser.add_argument("--n-gpu-layers", type=int, default=0, help="number of GPU layers")
    parser.add_argument("--temperature", type=float, default=0.1, help="generation temperature")
    parser.add_argument("--top-p", type=float, default=0.9, help="generation top-p")
    parser.add_argument("--max-tokens", type=int, default=256, help="completion token cap")
    parser.add_argument("--timeout-s", type=int, default=180, help="request timeout")
    parser.add_argument("--limit", type=int, default=0, help="limit number of cases (0 = all)")
    parser.add_argument(
        "--benchmark-mode",
        type=str,
        choices=["stateless", "prod-like"],
        default="stateless",
        help="stateless = strict quality benchmark, prod-like = warm session benchmark",
    )
    parser.add_argument(
        "--slot-id",
        type=int,
        default=0,
        help="slot id used for prod-like session reuse",
    )
    parser.add_argument(
        "--cache-prompt-hint",
        action="store_true",
        help="send cache_prompt=true hint in request payload",
    )
    parser.add_argument(
        "--skip-prod-warmup",
        action="store_true",
        help="skip initial warmup request in prod-like mode",
    )
    parser.add_argument(
        "--prod-like-user-only",
        action="store_true",
        help="prod-like advanced mode: send user turn only after warmup (faster, may reduce quality)",
    )
    parser.add_argument(
        "--decompose",
        action="store_true",
        help="use decomposer pipeline (multi-intent -> N single-intents)",
    )
    parser.add_argument(
        "--entity-filter",
        action="store_true",
        help="safety: override to do_nothing when model outputs unknown room/device/preset",
    )
    parser.add_argument("--no-start-server", action="store_true", help="reuse existing server")
    parser.add_argument("--no-warmup", action="store_true", help="disable server warmup")
    parser.add_argument("-q", "--quiet", action="store_true", help="quiet mode")
    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_REPORT),
        help="output JSON report path",
    )
    args = parser.parse_args()

    model_path = Path(args.model)
    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}")

    cases = load_cases(Path(args.cases))
    if args.limit > 0:
        cases = cases[: args.limit]

    contracts = load_json(Path(args.contracts))
    home_state = load_json(Path(args.home_state))
    aliases_payload = load_json(Path(args.aliases))

    tools_block = build_tools_block(contracts)
    knowledge_hint = build_knowledge_hint(home_state)
    system_prompt = build_system_prompt(Path(args.prompt), tools_block, knowledge_hint)
    decomp_prompt = ""
    if args.decompose:
        decomp_prompt = (BASE_DIR / "prompts" / "decomposer_prompt.txt").read_text(
            encoding="utf-8"
        )
        print("[MODE] Decomposer pipeline: multi -> N single-intents")
    if args.entity_filter:
        print("[MODE] Entity filter: unknown room/device/preset -> do_nothing (safety)")
    known_sets = build_known_sets(home_state, aliases_payload)
    allowed_tools = {tool["name"] for tool in contracts.get("tools", [])}

    base_url = f"http://{args.host}:{args.port}"
    server: Optional[LlamaServerProcess] = None

    try:
        if not args.no_start_server:
            server = LlamaServerProcess(
                llama_bin_dir=Path(args.llama_bin),
                model_path=model_path,
                host=args.host,
                port=args.port,
                n_ctx=args.n_ctx,
                n_gpu_layers=args.n_gpu_layers,
                no_warmup=args.no_warmup,
                log_dir=BASE_DIR / "logs",
            )
            print(f"[LOAD] Starting llama-server at {base_url}")
            server.start()
            print("[OK] llama-server is ready")
        if args.benchmark_mode == "prod-like":
            print(
                "[MODE] prod-like: session warm benchmark (not strictly comparable to stateless quality runs)"
            )
            if args.prod_like_user_only:
                print(
                    "[MODE] prod-like-user-only enabled: faster but can degrade parser reliability"
                )

        client = QwenParserClient(
            base_url=base_url,
            model_path=str(model_path),
            temperature=args.temperature,
            top_p=args.top_p,
            max_tokens=args.max_tokens,
            timeout_s=args.timeout_s,
            id_slot=args.slot_id if args.benchmark_mode == "prod-like" else None,
            cache_prompt_hint=args.cache_prompt_hint,
        )

        results: List[Dict[str, Any]] = []
        if args.benchmark_mode == "prod-like" and not args.skip_prod_warmup:
            warmup = client.process("ok", system_prompt, include_system=True)
            print(
                f"[WARMUP] prod-like session ready | "
                f"{warmup['latency_ms']:.0f}ms | tokens={warmup['tokens']}"
            )

        for case in cases:
            include_system = args.benchmark_mode == "stateless" or not args.prod_like_user_only
            if args.decompose:
                response = client.process_with_decompose(
                    case["user_input"], system_prompt, decomp_prompt, include_system=include_system
                )
            else:
                response = client.process(
                    case["user_input"], system_prompt, include_system=include_system
                )
            parsed_calls = response["calls"]
            if args.entity_filter and parsed_calls:
                parsed_calls = apply_entity_filter(parsed_calls, known_sets)
            valid = isinstance(parsed_calls, list) and len(parsed_calls) > 0
            score = evaluate_case(
                case=case,
                parsed_calls=parsed_calls,
                valid=valid,
                known=known_sets,
                allowed_tools=allowed_tools,
            )

            item = {
                "id": case["id"],
                "category": case["category"],
                "user_input": case["user_input"],
                "expected": case["expected"],
                "model_response": response["response"],
                "parsed_calls": parsed_calls,
                "latency_ms": round(response["latency_ms"], 2),
                "tokens": response["tokens"],
                "score": score,
            }
            results.append(item)

            if not args.quiet:
                status = "OK" if score["success"] else "FAIL"
                print(
                    f"[{status}] {case['id']} | {case['category']} | "
                    f"{response['latency_ms']:.0f}ms | {case['user_input']}"
                )

        summary = aggregate(results)
        print_console_summary(summary)

        ranked_failures = sorted(
            [x for x in results if not x["score"]["success"]],
            key=lambda x: sum(1 for v in x["score"].values() if v is False),
            reverse=True,
        )
        worst_failures = ranked_failures[:20]

        report = {
            "meta": {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "model": str(model_path),
                "decompose": args.decompose,
                "entity_filter": args.entity_filter,
                "benchmark_mode": args.benchmark_mode,
                "slot_id": args.slot_id if args.benchmark_mode == "prod-like" else None,
                "cache_prompt_hint": args.cache_prompt_hint,
                "prod_like_user_only": bool(args.prod_like_user_only),
                "cases_file": str(Path(args.cases).resolve()),
                "prompt_file": str(Path(args.prompt).resolve()),
                "contracts_file": str(Path(args.contracts).resolve()),
                "home_state_file": str(Path(args.home_state).resolve()),
                "aliases_file": str(Path(args.aliases).resolve()),
                "base_url": base_url,
            },
            "summary": summary,
            "worst_failures": worst_failures,
            "results": results,
        }

        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n[OK] Report saved: {output_path}")

    finally:
        if server:
            server.stop()


if __name__ == "__main__":
    main()

