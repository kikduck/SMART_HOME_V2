"""
Smart Home V2 - Admin API
=========================
API REST pour éditer : maison, alias, tools, prompt, presets.
Optimisé pour déploiement léger (Ryzen 5 Pro 2400G).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import re
import time
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import requests

import os

# En dev: parent.parent = SMART_HOME_V2. En Docker: SMART_HOME_BASE=/app
_DEFAULT = Path(__file__).resolve().parent.parent
BASE = Path(os.environ.get("SMART_HOME_BASE", str(_DEFAULT)))
KNOWLEDGE_DIR = BASE / "knowledge"
SCHEMAS_DIR = BASE / "schemas"
PROMPTS_DIR = BASE / "prompts"
PRESETS_DIR = KNOWLEDGE_DIR / "presets"
CONFIG_PATH = KNOWLEDGE_DIR / "config.json"
MODELS_DIR = BASE / "models"

app = FastAPI(title="Smart Home V2 Admin", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _read_json(path: Path) -> Any:
    if not path.exists():
        raise HTTPException(404, f"Fichier absent: {path.name}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _read_text(path: Path) -> str:
    if not path.exists():
        raise HTTPException(404, f"Fichier absent: {path.name}")
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Maison (home_state)
# ---------------------------------------------------------------------------
@app.get("/api/home")
def get_home() -> Dict[str, Any]:
    return _read_json(KNOWLEDGE_DIR / "home_state.json")


@app.put("/api/home")
def put_home(data: Dict[str, Any]) -> Dict[str, str]:
    _write_json(KNOWLEDGE_DIR / "home_state.json", data)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Alias
# ---------------------------------------------------------------------------
@app.get("/api/aliases")
def get_aliases() -> Dict[str, Any]:
    return _read_json(KNOWLEDGE_DIR / "aliases.json")


@app.put("/api/aliases")
def put_aliases(data: Dict[str, Any]) -> Dict[str, str]:
    _write_json(KNOWLEDGE_DIR / "aliases.json", data)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Tools (contracts)
# ---------------------------------------------------------------------------
@app.get("/api/tools")
def get_tools() -> Dict[str, Any]:
    return _read_json(SCHEMAS_DIR / "tools_contracts.json")


@app.put("/api/tools")
def put_tools(data: Dict[str, Any]) -> Dict[str, str]:
    _write_json(SCHEMAS_DIR / "tools_contracts.json", data)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
@app.get("/api/prompt")
def get_prompt() -> Dict[str, str]:
    return {"content": _read_text(PROMPTS_DIR / "system_prompt_v2.txt")}


@app.put("/api/prompt")
def put_prompt(payload: Dict[str, str]) -> Dict[str, str]:
    content = payload.get("content", "")
    _write_text(PROMPTS_DIR / "system_prompt_v2.txt", content)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Presets (JSON files)
# ---------------------------------------------------------------------------
@app.get("/api/presets")
def list_presets() -> Dict[str, Any]:
    """Retourne les presets depuis home_state + fichiers .json dans presets/."""
    home = _read_json(KNOWLEDGE_DIR / "home_state.json")
    presets = home.get("presets", {"lighting": {}, "global": {}})

    files: List[Dict[str, str]] = []
    if PRESETS_DIR.exists():
        for f in PRESETS_DIR.glob("*.json"):
            files.append({"name": f.stem, "path": str(f.relative_to(BASE))})

    return {"presets": presets, "files": files}


@app.get("/api/presets/{scope}/{name}")
def get_preset(scope: str, name: str) -> Dict[str, Any]:
    home = _read_json(KNOWLEDGE_DIR / "home_state.json")
    presets = home.get("presets", {})
    scope_data = presets.get(scope, {})
    if name not in scope_data:
        raise HTTPException(404, f"Preset {scope}/{name} introuvable")
    return {"scope": scope, "name": name, "data": scope_data[name]}


@app.get("/api/presets/{scope}/{name}/content")
def get_preset_content(scope: str, name: str) -> Dict[str, Any]:
    """Contenu du preset (knowledge/presets/{scope}_{name}.json) utilisé par les tools."""
    path = PRESETS_DIR / f"{scope}_{name}.json"
    if path.exists():
        data = _read_json(path)
        return {"scope": scope, "name": name, "content": data, "file": str(path.relative_to(BASE))}
    home = _read_json(KNOWLEDGE_DIR / "home_state.json")
    presets = home.get("presets", {})
    scope_data = presets.get(scope, {})
    data = scope_data.get(name, {})
    return {"scope": scope, "name": name, "content": data, "file": None}


@app.put("/api/presets/{scope}/{name}/content")
def put_preset_content(scope: str, name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Enregistre le contenu dans knowledge/presets/{scope}_{name}.json."""
    if scope not in ("lighting", "global"):
        raise HTTPException(400, "scope doit être lighting ou global")
    content = payload.get("content", payload.get("data", {}))
    if not isinstance(content, dict):
        content = {}
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    path = PRESETS_DIR / f"{scope}_{name}.json"
    _write_json(path, content)
    # Garde le preset listé dans home_state
    home = _read_json(KNOWLEDGE_DIR / "home_state.json")
    home.setdefault("presets", {"lighting": {}, "global": {}})
    home["presets"].setdefault(scope, {})
    home["presets"][scope][name] = {}  # registry; le contenu est dans le fichier
    _write_json(KNOWLEDGE_DIR / "home_state.json", home)
    return {"status": "ok", "file": str(path.relative_to(BASE))}


@app.put("/api/presets/{scope}/{name}")
def put_preset(scope: str, name: str, payload: Dict[str, Any]) -> Dict[str, str]:
    if scope not in ("lighting", "global"):
        raise HTTPException(400, "scope doit être lighting ou global")
    home = _read_json(KNOWLEDGE_DIR / "home_state.json")
    home.setdefault("presets", {"lighting": {}, "global": {}})
    home["presets"].setdefault(scope, {})
    home["presets"][scope][name] = payload.get("data", {})
    _write_json(KNOWLEDGE_DIR / "home_state.json", home)
    return {"status": "ok"}


@app.delete("/api/presets/{scope}/{name}")
def delete_preset(scope: str, name: str) -> Dict[str, str]:
    home = _read_json(KNOWLEDGE_DIR / "home_state.json")
    presets = home.get("presets", {})
    if scope in presets and name in presets[scope]:
        del presets[scope][name]
        _write_json(KNOWLEDGE_DIR / "home_state.json", home)
    path = PRESETS_DIR / f"{scope}_{name}.json"
    if path.exists():
        path.unlink()
    return {"status": "ok"}


@app.post("/api/presets/export")
def export_preset(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Exporte un preset en fichier .json dans knowledge/presets/."""
    scope = payload.get("scope", "global")
    name = payload.get("name", "")
    data = payload.get("data", {})
    if not name:
        raise HTTPException(400, "name requis")
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    path = PRESETS_DIR / f"{scope}_{name}.json"
    _write_json(path, {"scope": scope, "name": name, **data})
    return {"status": "ok", "path": str(path.relative_to(BASE)), "content": {"scope": scope, "name": name, **data}}


@app.post("/api/presets/import")
async def import_preset(file: UploadFile) -> Dict[str, Any]:
    """Importe un preset depuis un fichier .json."""
    if not file.filename or not file.filename.endswith(".json"):
        raise HTTPException(400, "Fichier .json requis")
    content = await file.read()
    try:
        data = json.loads(content.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"JSON invalide: {e}")
    scope = data.get("scope", "global")
    name = data.get("name", data.get("name", file.filename.replace(".json", "")))
    home = _read_json(KNOWLEDGE_DIR / "home_state.json")
    home.setdefault("presets", {"lighting": {}, "global": {}})
    home["presets"].setdefault(scope, {})
    payload = {k: v for k, v in data.items() if k not in ("scope", "name")}
    home["presets"][scope][name] = payload
    _write_json(KNOWLEDGE_DIR / "home_state.json", home)
    return {"status": "ok", "scope": scope, "name": name}


# ---------------------------------------------------------------------------
# Config (modèle, etc.)
# ---------------------------------------------------------------------------
DEFAULT_MODELS = [
    {"id": "Qwen3.5-2B-Q6_K", "file": "Qwen3.5-2B-Q6_K.gguf", "source": "unsloth/Qwen3.5-2B-GGUF", "size": "1.5 GB"},
    {"id": "Qwen3.5-2B-Q4_K_M", "file": "Qwen3.5-2B-Q4_K_M.gguf", "source": "unsloth/Qwen3.5-2B-GGUF", "size": "1.2 GB"},
    {"id": "Qwen3.5-2B-Q5_K_M", "file": "Qwen3.5-2B-Q5_K_M.gguf", "source": "unsloth/Qwen3.5-2B-GGUF", "size": "1.3 GB"},
]


@app.get("/api/config")
def get_config() -> Dict[str, Any]:
    """Config serveur (modèle, etc.)."""
    if CONFIG_PATH.exists():
        data = _read_json(CONFIG_PATH)
    else:
        data = {"model_id": "Qwen3.5-2B-Q6_K", "model_path": "", "llama_port": 8085}
    data.setdefault("model_id", "Qwen3.5-2B-Q6_K")
    data.setdefault("model_path", "")
    data.setdefault("llama_port", 8085)
    data.setdefault("llama_base_url", f"http://127.0.0.1:{data.get('llama_port', 8085)}")
    data["available_models"] = DEFAULT_MODELS
    models_in_dir: List[Dict[str, str]] = []
    if MODELS_DIR.exists():
        for f in MODELS_DIR.glob("*.gguf"):
            models_in_dir.append({"id": f.stem, "file": f.name, "path": str(f)})
    data["models_in_dir"] = models_in_dir
    return data


@app.put("/api/config")
def put_config(payload: Dict[str, Any]) -> Dict[str, str]:
    """Met à jour la config."""
    if CONFIG_PATH.exists():
        data = _read_json(CONFIG_PATH)
    else:
        data = {}
    data["model_id"] = payload.get("model_id", data.get("model_id", "Qwen3.5-2B-Q6_K"))
    data["model_path"] = payload.get("model_path", data.get("model_path", ""))
    data["llama_port"] = payload.get("llama_port", data.get("llama_port", 8085))
    data["llama_base_url"] = payload.get("llama_base_url", data.get("llama_base_url", ""))
    _write_json(CONFIG_PATH, data)
    return {"status": "ok"}


@app.get("/api/models")
def list_models() -> Dict[str, Any]:
    """Liste les modèles disponibles (défaut + dossier models/)."""
    return {"default": DEFAULT_MODELS, "in_dir": [] if not MODELS_DIR.exists() else [{"id": f.stem, "file": f.name} for f in MODELS_DIR.glob("*.gguf")]}


# ---------------------------------------------------------------------------
# Parse (voice-to-text → tool calls)
# ---------------------------------------------------------------------------
def _build_tools_block(contracts: Dict[str, Any]) -> str:
    lines = []
    for tool in contracts.get("tools", []):
        name = tool["name"]
        req = ", ".join(tool.get("arguments", {}).get("required", []))
        opt = ", ".join(tool.get("arguments", {}).get("optional", []))
        sig = name + "(" + req + (", " + opt + "?" if opt else "") + ")"
        lines.append(f"- {sig}: {tool.get('description', '').strip()}")
    return "\n".join(lines)


def _build_knowledge_hint(home_state: Dict[str, Any]) -> str:
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
        f"rooms={rooms}\nfixtures={sorted(set(fixtures))}\ndevices={sorted(set(devices))}\n"
        f"lighting_presets={lp}\nglobal_presets={gp}\nsensor_types={sensors}"
    )


def _parse_llm_response(text: str) -> Optional[Any]:
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start, end = s.find(open_c), s.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(s[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None


@app.post("/api/parse")
def parse_instruction(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Envoie une instruction voice-to-text au modèle et retourne les tool calls parsés.
    Body: {"text": "allume le salon", "decompose": false}
    """
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text requis")
    use_decompose = payload.get("decompose", False)

    config = _read_json(CONFIG_PATH) if CONFIG_PATH.exists() else {}
    base_url = os.environ.get("LLAMA_BASE_URL") or (config.get("llama_base_url") or "").rstrip("/")
    if not base_url:
        base_url = f"http://127.0.0.1:{config.get('llama_port', 8085)}"

    home_state = _read_json(KNOWLEDGE_DIR / "home_state.json")
    contracts = _read_json(SCHEMAS_DIR / "tools_contracts.json")
    prompt_tpl = _read_text(PROMPTS_DIR / "system_prompt_v2.txt")
    tools_block = _build_tools_block(contracts)
    knowledge_hint = _build_knowledge_hint(home_state)
    system_prompt = prompt_tpl.replace("{{TOOLS_BLOCK}}", tools_block).replace("{{KNOWLEDGE_HINT}}", knowledge_hint)

    try:
        r = requests.get(f"{base_url}/health", timeout=3)
        if r.status_code != 200:
            raise HTTPException(503, "llama-server injoignable")
    except requests.RequestException as e:
        raise HTTPException(503, f"llama-server injoignable: {e}")

    req_payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
        "temperature": 0.0,
        "top_p": 0.9,
        "max_tokens": 128,
        "timings_per_token": True,
    }

    t0 = time.perf_counter()
    try:
        resp = requests.post(f"{base_url}/v1/chat/completions", json=req_payload, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise HTTPException(502, f"Erreur llama-server: {e}")
    wall_ms = (time.perf_counter() - t0) * 1000

    data = resp.json()
    content_raw = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    content = " ".join(
        item.get("text", "") for item in content_raw
        if isinstance(content_raw, list) and isinstance(item, dict)
    ) if isinstance(content_raw, list) else str(content_raw)

    parsed = _parse_llm_response(content)
    items = parsed if isinstance(parsed, list) else ([parsed] if isinstance(parsed, dict) else [])
    calls = [x for x in items if isinstance(x, dict) and (x.get("tool") or x.get("action"))]

    return {
        "parsed": calls if calls else None,
        "raw": content,
        "wall_ms": round(wall_ms, 0),
    }


# ---------------------------------------------------------------------------
# Rules (optionnel)
# ---------------------------------------------------------------------------
@app.get("/api/rules")
def get_rules() -> Dict[str, Any]:
    return _read_json(KNOWLEDGE_DIR / "rules.json")


@app.put("/api/rules")
def put_rules(data: Dict[str, Any]) -> Dict[str, str]:
    _write_json(KNOWLEDGE_DIR / "rules.json", data)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Static (UI)
# ---------------------------------------------------------------------------
static_dir = Path(__file__).resolve().parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    def index():
        return FileResponse(static_dir / "index.html")
