"""
Smart Home V2 - Test interactif
================================
Simule la prod avec 3 modes :
  --mode gpu         : RTX 5090, build CUDA b8189  (dev rapide)
  --mode cpu         : CPU-only, build b8184        (reference lente)
  --mode ubuntu      : CPU limité 4 threads          (simulation prod Ryzen 5 Pro 2400G)

Usage :
  python SMART_HOME_V2/test_interactive.py --mode gpu
  python SMART_HOME_V2/test_interactive.py --mode ubuntu
  python SMART_HOME_V2/test_interactive.py --mode gpu --no-start-server --port 8083
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# Import entity filter from benchmark (safety: unknown room/device/preset -> do_nothing)
import importlib.util
_bench_path = Path(__file__).resolve().parent / "benchmarks" / "run_benchmark_v2.py"
_spec = importlib.util.spec_from_file_location("run_benchmark_v2", _bench_path)
_bench_mod = importlib.util.module_from_spec(_spec) if _spec else None
if _bench_mod and _spec:
    try:
        _spec.loader.exec_module(_bench_mod)
        apply_entity_filter = getattr(_bench_mod, "apply_entity_filter", None)
        build_known_sets = getattr(_bench_mod, "build_known_sets", None)
    except Exception:
        apply_entity_filter = None
        build_known_sets = None
else:
    apply_entity_filter = None
    build_known_sets = None

# Force UTF-8 sur stdout/stderr (Windows cmd/PowerShell)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent

MODEL_PATH        = Path(r"D:\PROG\TEST\SMART_HOME\gguf_models\Qwen3.5-2B-Q6_K.gguf")
LLAMA_BIN_CUDA    = Path(r"D:\PROG\TEST\SMART_HOME\llama-cuda-bin")
LLAMA_BIN_CPU     = Path(r"D:\PROG\TEST\SMART_HOME\llama-b8184-bin")

PROMPT_PATH       = BASE_DIR / "prompts" / "system_prompt_v2.txt"
DECOMPOSER_PATH   = BASE_DIR / "prompts" / "decomposer_prompt.txt"
CONTRACTS_PATH    = BASE_DIR / "schemas" / "tools_contracts.json"
HOME_STATE_PATH   = BASE_DIR / "knowledge" / "home_state.json"
ALIASES_PATH      = BASE_DIR / "knowledge" / "aliases.json"
LOG_DIR           = BASE_DIR / "logs"

# ---------------------------------------------------------------------------
# Profils de mode
# ---------------------------------------------------------------------------
MODES: Dict[str, Dict[str, Any]] = {
    "gpu": {
        "label": "GPU (RTX 5090 CUDA b8189)",
        "color": "\033[92m",   # vert
        "llama_bin": LLAMA_BIN_CUDA,
        "n_gpu_layers": -1,
        "n_threads": None,     # laisser llama-server décider
        "port": 8083,
    },
    "cpu": {
        "label": "CPU-only (b8184 - référence lente)",
        "color": "\033[93m",   # jaune
        "llama_bin": LLAMA_BIN_CPU,
        "n_gpu_layers": 0,
        "n_threads": None,
        "port": 8084,
    },
    "ubuntu": {
        "label": "Ubuntu-like (CPU, 4 threads - Ryzen 5 Pro 2400G simulé)",
        "color": "\033[94m",   # bleu
        "llama_bin": LLAMA_BIN_CPU,
        "n_gpu_layers": 0,
        "n_threads": 4,
        "port": 8085,
    },
}

# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
WHITE  = "\033[97m"


def c(text: str, color: str) -> str:
    return f"{color}{text}{RESET}"


# ---------------------------------------------------------------------------
# Chargement des fichiers de configuration
# ---------------------------------------------------------------------------
def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_tools_block(contracts: Dict[str, Any]) -> str:
    lines: List[str] = []
    for tool in contracts.get("tools", []):
        name = tool["name"]
        required = ", ".join(tool.get("arguments", {}).get("required", []))
        optional = ", ".join(tool.get("arguments", {}).get("optional", []))
        sig = name + "("
        if required:
            sig += required
        if optional:
            if required:
                sig += ", "
            sig += optional + "?"
        sig += ")"
        lines.append(f"- {sig}: {tool.get('description', '').strip()}")
    return "\n".join(lines)


def build_knowledge_hint(home_state: Dict[str, Any]) -> str:
    rooms = sorted(home_state.get("rooms", {}).keys())
    fixtures, devices = [], []
    for rp in home_state.get("rooms", {}).values():
        fixtures.extend(rp.get("lights", []))
        devices.extend(rp.get("devices", []))
    presets = home_state.get("presets", {})
    lp = sorted((presets.get("lighting", {}) or {}).keys())
    gp = sorted((presets.get("global", {}) or {}).keys())
    sensors = sorted((home_state.get("sensor_types", {}) or {}).keys())
    return (
        f"rooms={rooms}\n"
        f"fixtures={sorted(set(fixtures))}\n"
        f"devices={sorted(set(devices))}\n"
        f"lighting_presets={lp}\n"
        f"global_presets={gp}\n"
        f"sensor_types={sensors}"
    )


def build_system_prompt(tools_block: str, knowledge_hint: str) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = template.replace("{{TOOLS_BLOCK}}", tools_block)
    prompt = prompt.replace("{{KNOWLEDGE_HINT}}", knowledge_hint)
    return prompt


# ---------------------------------------------------------------------------
# Parsing JSON réponse
# ---------------------------------------------------------------------------
def strip_code_fences(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def parse_response(text: str) -> Optional[Any]:
    candidate = strip_code_fences(text)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    for opening, closing in (("{", "}"), ("[", "]")):
        start = candidate.find(opening)
        end = candidate.rfind(closing)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None


def format_calls(parsed: Any) -> str:
    """Formate les tool calls de manière lisible."""
    if parsed is None:
        return c("(aucun appel parsé)", RED)

    items = parsed if isinstance(parsed, list) else [parsed]
    lines = []
    for i, item in enumerate(items, 1):
        if not isinstance(item, dict):
            lines.append(f"  [{i}] {c(str(item), YELLOW)}")
            continue
        tool = item.get("tool") or item.get("action") or "?"
        args = item.get("args", {})
        if not isinstance(args, dict):
            args = {}
        args_str = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in args.items())
        color = GREEN if tool not in ("do_nothing",) else YELLOW
        prefix = f"  [{i}] " if len(items) > 1 else "  "
        lines.append(f"{prefix}{c(tool, color)}({c(args_str, WHITE)})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Démarrage / arrêt du serveur llama
# ---------------------------------------------------------------------------
class LlamaServer:
    def __init__(
        self,
        mode_cfg: Dict[str, Any],
        n_ctx: int = 2048,
        model_path: Optional[Path] = None,
        ubatch_size: Optional[int] = None,
    ) -> None:
        self.cfg = mode_cfg
        self.n_ctx = n_ctx
        self.model_path = model_path or MODEL_PATH
        self.ubatch_size = ubatch_size
        self.process: Optional[subprocess.Popen] = None
        self.log_path: Optional[Path] = None

    @property
    def port(self) -> int:
        return self.cfg["port"]

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self, timeout_s: int = 120) -> None:
        llama_bin: Path = self.cfg["llama_bin"]
        exe = llama_bin / "llama-server.exe"
        if not exe.exists():
            raise FileNotFoundError(f"llama-server.exe introuvable : {exe}")

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.log_path = LOG_DIR / f"interactive_{self.cfg['port']}_{int(time.time())}.log"
        log_file = self.log_path.open("w", encoding="utf-8")

        cmd = [
            str(exe), "-m", str(self.model_path),
            "--host", "127.0.0.1", "--port", str(self.port),
            "-ngl", str(self.cfg["n_gpu_layers"]),
            "-c", str(self.n_ctx),
            "--jinja", "--no-warmup",
            "--parallel", "1",
            "--cache-prompt",
        ]
        if self.ubatch_size is not None:
            cmd += ["-ub", str(self.ubatch_size)]
        if self.cfg.get("n_threads") is not None:
            cmd += ["-t", str(self.cfg["n_threads"]),
                    "-tb", str(self.cfg["n_threads"])]

        print(c(f"  Démarrage serveur sur port {self.port}...", DIM))
        print(c(f"  Log : {self.log_path}", DIM))

        self.process = subprocess.Popen(
            cmd,
            cwd=str(llama_bin),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.process.poll() is not None:
                log_file.close()
                raise RuntimeError(
                    f"llama-server s'est arrêté prématurément (code {self.process.returncode}). "
                    f"Voir : {self.log_path}"
                )
            try:
                r = requests.get(f"{self.base_url}/health", timeout=2)
                if r.status_code == 200:
                    log_file.close()
                    return
            except requests.RequestException:
                pass
            time.sleep(1)
            print(".", end="", flush=True)

        log_file.close()
        raise TimeoutError(f"Timeout démarrage serveur ({timeout_s}s). Voir : {self.log_path}")

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def is_ready(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/health", timeout=3)
            return r.status_code == 200
        except requests.RequestException:
            return False


# ---------------------------------------------------------------------------
# Décomposeur (single vs multi-intent)
# ---------------------------------------------------------------------------
def call_decomposer(
    base_url: str,
    user_input: str,
    max_tokens: int = 64,
    temperature: float = 0.0,
    timeout_s: int = 30,
) -> Dict[str, Any]:
    """Appelle le décomposeur. Retourne {type, intent} ou {type, intents}."""
    decomp_prompt = DECOMPOSER_PATH.read_text(encoding="utf-8")
    payload = {
        "messages": [
            {"role": "system", "content": decomp_prompt},
            {"role": "user", "content": user_input},
        ],
        "temperature": temperature,
        "top_p": 0.9,
        "max_tokens": max_tokens,
        "timings_per_token": True,
    }
    t0 = time.perf_counter()
    resp = requests.post(
        f"{base_url}/v1/chat/completions",
        json=payload,
        timeout=timeout_s,
    )
    wall_ms = (time.perf_counter() - t0) * 1000
    resp.raise_for_status()
    data = resp.json()
    content_raw = data["choices"][0]["message"]["content"]
    if isinstance(content_raw, list):
        content = " ".join(
            item.get("text", "") for item in content_raw if isinstance(item, dict)
        )
    else:
        content = str(content_raw)
    parsed = parse_response(content)
    out: Dict[str, Any] = parsed if isinstance(parsed, dict) else {"type": "single", "intent": user_input}
    timings = data.get("timings", {})
    usage = data.get("usage", {})
    out["_timings"] = {
        "wall_ms": wall_ms,
        "prefill_ms": timings.get("prompt_ms", 0),
        "gen_ms": timings.get("predicted_ms", 0),
        "prefill_tps": timings.get("prompt_per_second", 0),
        "gen_tps": timings.get("predicted_per_second", 0),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
    }
    return out


# Mots de liaison / passages qui suggèrent plusieurs intents (transcript voice-to-text)
_MULTI_INTENT_PATTERNS = (
    " et ", " puis ", " ensuite ", " et aussi ", " et en plus ",
    " ou bien ", " d'abord ", " puis après ", " et après ",
    ",", ";", " ou ", " sinon ",
)

def _likely_single_intent(text: str) -> bool:
    """Heuristique : aucun mot de passage multi-intent -> probablement single intent."""
    t = text.strip().lower()
    return not any(p in t for p in _MULTI_INTENT_PATTERNS)


def call_model_with_decompose(
    base_url: str,
    system_prompt: str,
    user_input: str,
    max_tokens: int = 128,
    temperature: float = 0.0,
    top_p: float = 0.9,
    timeout_s: int = 60,
    skip_decomposer_for_single: bool = True,
) -> Dict[str, Any]:
    """
    Pipeline : décomposeur -> parseur (N appels single-intent).
    Si skip_decomposer_for_single et phrase sans 'et'/'puis'/',' -> parser direct (gain ~3-5s).
    """
    if skip_decomposer_for_single and _likely_single_intent(user_input):
        r = call_model(base_url, system_prompt, user_input, max_tokens, temperature, top_p, timeout_s)
        parsed = r.get("parsed")
        calls = [parsed] if isinstance(parsed, dict) else (parsed if isinstance(parsed, list) else [])
        return {
            "content": json.dumps(calls, ensure_ascii=False) if calls else "",
            "parsed": [c for c in calls if isinstance(c, dict) and (c.get("tool") or c.get("action"))] or None,
            "wall_ms": r.get("wall_ms", 0),
            "prefill_ms": r.get("prefill_ms", 0),
            "prefill_tps": r.get("prefill_tps", 0),
            "gen_ms": r.get("gen_ms", 0),
            "gen_tps": r.get("gen_tps", 0),
            "prompt_tokens": r.get("prompt_tokens", 0),
            "completion_tokens": r.get("completion_tokens", 0),
        }

    decomp = call_decomposer(base_url, user_input, max_tokens=64, temperature=0, timeout_s=timeout_s)
    intents: List[str] = []
    if decomp.get("type") == "multi" and isinstance(decomp.get("intents"), list):
        intents = [str(s).strip() for s in decomp["intents"] if s]
    if not intents:
        intents = [decomp.get("intent", user_input) or user_input]

    all_calls: List[Dict[str, Any]] = []
    total_wall = 0
    total_prefill = 0
    total_gen = 0
    total_ptok = 0
    total_ctok = 0

    t_decomp = decomp.get("_timings", {})
    total_wall += t_decomp.get("wall_ms", 0)
    total_prefill += t_decomp.get("prefill_ms", 0)
    total_gen += t_decomp.get("gen_ms", 0)
    total_ptok += t_decomp.get("prompt_tokens", 0)
    total_ctok += t_decomp.get("completion_tokens", 0)

    for intent in intents:
        r = call_model(
            base_url=base_url,
            system_prompt=system_prompt,
            user_input=intent,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            timeout_s=timeout_s,
        )
        total_wall += r.get("wall_ms", 0)
        total_prefill += r.get("prefill_ms", 0)
        total_gen += r.get("gen_ms", 0)
        total_ptok += r.get("prompt_tokens", 0)
        total_ctok += r.get("completion_tokens", 0)
        parsed = r.get("parsed")
        if parsed is not None:
            items = parsed if isinstance(parsed, list) else [parsed]
            for item in items:
                if isinstance(item, dict) and (item.get("tool") or item.get("action")):
                    all_calls.append(item)

    total_ms = total_prefill + total_gen
    prefill_tps = (total_ptok / (total_prefill / 1000)) if total_prefill > 0 else 0
    gen_tps = (total_ctok / (total_gen / 1000)) if total_gen > 0 else 0

    return {
        "content": json.dumps(all_calls, ensure_ascii=False) if all_calls else "",
        "parsed": all_calls if all_calls else None,
        "wall_ms": total_wall,
        "prefill_ms": total_prefill,
        "prefill_tps": prefill_tps,
        "gen_ms": total_gen,
        "gen_tps": gen_tps,
        "prompt_tokens": total_ptok,
        "completion_tokens": total_ctok,
    }


# ---------------------------------------------------------------------------
# Client requête
# ---------------------------------------------------------------------------
def call_model(
    base_url: str,
    system_prompt: str,
    user_input: str,
    max_tokens: int = 128,
    temperature: float = 0.0,
    top_p: float = 0.9,
    timeout_s: int = 60,
) -> Dict[str, Any]:
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ],
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        "timings_per_token": True,
    }

    t0 = time.perf_counter()
    resp = requests.post(
        f"{base_url}/v1/chat/completions",
        json=payload,
        timeout=timeout_s,
    )
    wall_ms = (time.perf_counter() - t0) * 1000

    resp.raise_for_status()
    data = resp.json()

    content_raw = data["choices"][0]["message"]["content"]
    if isinstance(content_raw, list):
        content = " ".join(
            item.get("text", "") for item in content_raw if isinstance(item, dict)
        )
    else:
        content = str(content_raw)

    timings = data.get("timings", {})
    usage = data.get("usage", {})

    return {
        "content": content,
        "parsed": parse_response(content),
        "wall_ms": wall_ms,
        "prefill_ms": timings.get("prompt_ms", 0),
        "prefill_tps": timings.get("prompt_per_second", 0),
        "gen_ms": timings.get("predicted_ms", 0),
        "gen_tps": timings.get("predicted_per_second", 0),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
    }


# ---------------------------------------------------------------------------
# Affichage d'un résultat
# ---------------------------------------------------------------------------
def print_result(result: Dict[str, Any], mode_color: str) -> None:
    wall = result["wall_ms"]
    pfill = result.get("prefill_ms", 0)
    pfill_tps = result.get("prefill_tps", 0)
    gen = result.get("gen_ms", 0)
    gen_tps = result.get("gen_tps", 0)
    ptok = result.get("prompt_tokens", 0)
    ctok = result.get("completion_tokens", 0)

    total = pfill + gen
    if total == 0 and wall > 0:
        gen = wall
        total = wall
        gen_tps = (ctok / (gen / 1000)) if gen > 0 else 0

    # Timing bar
    bar_width = 40
    if total > 0:
        pfill_chars = max(0, int(bar_width * pfill / total))
        gen_chars = max(0, bar_width - pfill_chars)
        if pfill_chars + gen_chars == 0:
            gen_chars = bar_width
    else:
        pfill_chars = gen_chars = bar_width // 2

    bar_prefill = c("#" * pfill_chars, CYAN)
    bar_gen = c("#" * gen_chars, GREEN)

    print()
    print(c("+- Résultat ----------------------------------------------", DIM))
    print(format_calls(result["parsed"]))
    print()
    print(c("+- Timings -----------------------------------------------", DIM))
    print(f"  {bar_prefill}{bar_gen}")
    print(
        f"  {c('Prefill', CYAN)} {pfill:.0f}ms ({pfill_tps:.0f} tok/s, {ptok} tok)  "
        f"{c('Génération', GREEN)} {gen:.0f}ms ({gen_tps:.1f} tok/s, {ctok} tok)  "
        f"{c('-> Total', mode_color)} {c(f'{wall:.0f}ms', BOLD)}"
    )
    print(c("+---------------------------------------------------------", DIM))


def print_raw(result: Dict[str, Any]) -> None:
    print()
    print(c("+- Réponse brute ------------------------------------------", DIM))
    print(f"  {c(result['content'], YELLOW)}")
    print(c("+----------------------------------------------------------", DIM))


# ---------------------------------------------------------------------------
# Aide intégrée
# ---------------------------------------------------------------------------
HELP_TEXT = """
Commandes spéciales :
  /quit  ou  /exit    Quitter
  /decompose          Activer/désactiver le pipeline décomposeur (multi->single)
  /raw                Afficher la réponse brute du prochain appel
  /tokens N           Changer max_tokens (défaut 128)
  /temp T             Changer temperature (défaut 0.0)
  /info               Afficher config courante
  /knowledge          Afficher le résumé knowledge
  /benchmark          Lancer le benchmark rapide (26 cas)
  /help               Afficher cette aide

Exemples de commandes testées :
  allume le salon
  mets 21 degres dans la chambre
  eteins toutes les lumieres et baisse le chauffage a 18
  quelle est la temperature du salon ?
  allume la tele et mets le salon en cinema
  qui suis-je ?
  allume l atelier  (entité inconnue -> get_current_knowledge)
"""


# ---------------------------------------------------------------------------
# REPL principal
# ---------------------------------------------------------------------------
def run_repl(
    base_url: str,
    system_prompt: str,
    knowledge_hint: str,
    mode_cfg: Dict[str, Any],
    use_decompose: bool = False,
    use_entity_filter: bool = False,
    known_sets: Optional[Dict[str, Any]] = None,
    log_path: Optional[Path] = None,
) -> None:
    mode_color: str = mode_cfg["color"]
    mode_label: str = mode_cfg["label"]

    max_tokens = 128
    temperature = 0.0
    show_raw_next = False
    decompose = use_decompose

    print()
    print(c("=" * 62, mode_color))
    print(c(f"  Smart Home V2 - Mode : {mode_label}", BOLD))
    print(c(f"  Serveur : {base_url}", DIM))
    decomp_status = c("ON", GREEN) if decompose else c("OFF", DIM)
    filter_status = c("ON", GREEN) if use_entity_filter else c("OFF", DIM)
    print(c(f"  Décomposeur : {decomp_status}  |  Entity filter : {filter_status}", DIM))
    print(c("  Tapez /help pour l'aide, /quit pour quitter", DIM))
    print(c("=" * 62, mode_color))
    print()

    while True:
        try:
            user_input = input(c("▶ ", mode_color)).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAu revoir.")
            break

        if not user_input:
            continue

        # Commandes spéciales
        if user_input.lower() in ("/quit", "/exit", "quit", "exit"):
            print("Au revoir.")
            break

        if user_input.lower() == "/help":
            print(HELP_TEXT)
            continue

        if user_input.lower() == "/raw":
            show_raw_next = True
            print(c("  [raw activé pour la prochaine requête]", DIM))
            continue

        if user_input.lower() == "/info":
            print(f"  Mode       : {c(mode_label, mode_color)}")
            print(f"  URL        : {base_url}")
            print(f"  Décomposeur: {c('ON', GREEN) if decompose else c('OFF', DIM)}")
            print(f"  max_tokens : {max_tokens}")
            print(f"  temperature: {temperature}")
            print(f"  Prompt     : {len(system_prompt)} chars")
            continue

        if user_input.lower() == "/knowledge":
            print(c("  Knowledge hint :", DIM))
            for line in knowledge_hint.splitlines():
                print(f"    {line}")
            continue

        if user_input.lower() == "/decompose":
            decompose = not decompose
            status = c("activé", GREEN) if decompose else c("désactivé", DIM)
            print(c(f"  Décomposeur {status}", DIM))
            continue

        if user_input.lower() == "/benchmark":
            _run_quick_benchmark(base_url, system_prompt, use_decompose=decompose)
            continue

        m = re.match(r"^/tokens\s+(\d+)$", user_input, re.IGNORECASE)
        if m:
            max_tokens = int(m.group(1))
            print(c(f"  max_tokens = {max_tokens}", DIM))
            continue

        m = re.match(r"^/temp\s+([\d.]+)$", user_input, re.IGNORECASE)
        if m:
            temperature = float(m.group(1))
            print(c(f"  temperature = {temperature}", DIM))
            continue

        # Appel modèle
        print(c("  ...", DIM), end="\r")
        try:
            if decompose:
                result = call_model_with_decompose(
                    base_url=base_url,
                    system_prompt=system_prompt,
                    user_input=user_input,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            else:
                result = call_model(
                    base_url=base_url,
                    system_prompt=system_prompt,
                    user_input=user_input,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
        except requests.exceptions.ConnectionError as e:
            err = str(e)
            if "10054" in err or "ConnectionResetError" in err or "refusée" in err or "refused" in err.lower():
                print(c("  Erreur : serveur injoignable (crash ou arrêt). Vérifiez le log.", RED))
                if log_path and log_path.exists():
                    print(c(f"  Log : {log_path}", DIM))
            else:
                print(c(f"  Erreur connexion : {e}", RED))
            continue
        except requests.RequestException as e:
            print(c(f"  Erreur serveur : {e}", RED))
            continue

        # Filtre de sécurité: unknown room/device/preset -> do_nothing
        if use_entity_filter and known_sets and apply_entity_filter and result.get("parsed"):
            filtered = apply_entity_filter(result["parsed"], known_sets)
            if filtered is not None:
                result = {**result, "parsed": filtered}

        if show_raw_next:
            print_raw(result)
            show_raw_next = False

        print_result(result, mode_color)


# ---------------------------------------------------------------------------
# Mini-benchmark intégré
# ---------------------------------------------------------------------------
QUICK_CASES = [
    ("allume le salon",                        "single"),
    ("mets 21 degres dans la chambre",         "single"),
    ("eteins la cuisine et allume le salon",   "multi"),
    ("eteins toutes les lumieres",             "global"),
    ("raconte une blague",                     "hors-scope"),
    ("allume l atelier",                       "unknown"),
]


def _run_quick_benchmark(base_url: str, system_prompt: str, use_decompose: bool = False) -> None:
    print()
    print(c("+- Mini-benchmark (6 cas) ---------------------------------", DIM))
    if use_decompose:
        print(c("  Mode décomposeur : ON", DIM))
    total_ms = 0
    caller = call_model_with_decompose if use_decompose else call_model
    for prompt, category in QUICK_CASES:
        try:
            r = caller(base_url, system_prompt, prompt, max_tokens=64, temperature=0)
            ms = r["wall_ms"]
            total_ms += ms
            calls_str = format_calls(r["parsed"]).strip()
            status = c("OK", GREEN)
            print(f"  {status}  {category:12} {ms:5.0f}ms  {prompt[:30]:30}  {calls_str}")
        except Exception as e:
            print(f"  {c('ERR', RED)} {category:12} {str(e)[:60]}")
    avg = total_ms / len(QUICK_CASES)
    print(c(f"  Moyenne : {avg:.0f}ms/requête  --  Total : {total_ms:.0f}ms", DIM))
    print(c("+----------------------------------------------------------", DIM))
    print()


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test interactif Smart Home V2 (GPU / CPU / Ubuntu-like)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples :
  python SMART_HOME_V2/test_interactive.py --mode gpu
  python SMART_HOME_V2/test_interactive.py --mode ubuntu
  python SMART_HOME_V2/test_interactive.py --mode gpu --no-start-server --port 8083
        """,
    )
    parser.add_argument(
        "--mode",
        choices=list(MODES.keys()),
        default="gpu",
        help="Mode de simulation (gpu / cpu / ubuntu)",
    )
    parser.add_argument(
        "--no-start-server",
        action="store_true",
        help="Ne pas démarrer de serveur (utiliser un serveur existant)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port du serveur (remplace le défaut du mode)",
    )
    parser.add_argument(
        "--n-ctx",
        type=int,
        default=2048,
        help="Taille du contexte (défaut 2048, min pour parser+knowledge)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Chemin du modèle GGUF (remplace MODEL_PATH)",
    )
    parser.add_argument(
        "--ubatch",
        type=int,
        default=None,
        help="Taille ubatch serveur (-ub), ex. 1024 pour mode ubuntu",
    )
    parser.add_argument(
        "--decompose",
        action="store_true",
        help="Activer le pipeline décomposeur (multi-intent -> N single-intents)",
    )
    parser.add_argument(
        "--entity-filter",
        action="store_true",
        help="Sécurité: unknown room/device/preset -> do_nothing",
    )
    args = parser.parse_args()

    mode_cfg = MODES[args.mode].copy()
    if args.port is not None:
        mode_cfg["port"] = args.port

    print()
    print(c(f"Smart Home V2 - Test interactif", BOLD))
    print(c(f"Mode : {mode_cfg['label']}", mode_cfg["color"]))
    print()

    # Chargement des fichiers
    print(c("Chargement des fichiers de configuration...", DIM))
    contracts   = load_json(CONTRACTS_PATH)
    home_state  = load_json(HOME_STATE_PATH)
    aliases     = load_json(ALIASES_PATH)
    tools_block    = build_tools_block(contracts)
    knowledge_hint = build_knowledge_hint(home_state)
    system_prompt  = build_system_prompt(tools_block, knowledge_hint)
    if args.entity_filter and not build_known_sets:
        print(c("  --entity-filter ignoré (import run_benchmark_v2 échoué)", RED))
    known_sets = build_known_sets(home_state, aliases) if build_known_sets and args.entity_filter else None
    print(c(f"  System prompt : {len(system_prompt)} chars / ~{len(system_prompt)//4} tokens estimés", DIM))

    # Serveur
    server: Optional[LlamaServer] = None
    base_url = f"http://127.0.0.1:{mode_cfg['port']}"

    if args.no_start_server:
        print(c(f"Mode --no-start-server : connexion à {base_url}...", DIM))
        # Vérifier que le serveur tourne
        try:
            r = requests.get(f"{base_url}/health", timeout=5)
            if r.status_code != 200:
                print(c(f"  Serveur indisponible (HTTP {r.status_code})", RED))
                sys.exit(1)
            print(c(f"  Serveur OK !", GREEN))
        except requests.RequestException as e:
            print(c(f"  Impossible de joindre le serveur : {e}", RED))
            sys.exit(1)
    else:
        # Vérifier d'abord si un serveur tourne déjà sur ce port
        try:
            r = requests.get(f"{base_url}/health", timeout=2)
            if r.status_code == 200:
                print(c(f"  Serveur déjà actif sur le port {mode_cfg['port']}, réutilisation.", GREEN))
            else:
                raise requests.RequestException("not 200")
        except requests.RequestException:
            # Démarrer le serveur
            model_path = Path(args.model) if args.model else MODEL_PATH
            ubatch = args.ubatch
            if ubatch is None and args.mode == "ubuntu":
                ubatch = 1024  # optimise latence en mode ubuntu
            server = LlamaServer(
                mode_cfg, n_ctx=args.n_ctx,
                model_path=model_path,
                ubatch_size=ubatch,
            )
            try:
                server.start()
                print(c("\n  Serveur démarré !", GREEN))
            except (FileNotFoundError, TimeoutError, RuntimeError) as e:
                print(c(f"\n  Erreur démarrage serveur : {e}", RED))
                sys.exit(1)

    try:
        run_repl(
            base_url, system_prompt, knowledge_hint, mode_cfg,
            use_decompose=args.decompose,
            use_entity_filter=args.entity_filter,
            known_sets=known_sets,
            log_path=server.log_path if server else None,
        )
    finally:
        if server:
            print(c("\nArrêt du serveur...", DIM))
            server.stop()


if __name__ == "__main__":
    main()
