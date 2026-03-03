# SMART_HOME_V2

Refonte propre et separee du projet Smart Home, orientee parser outille (MCP-grade) pour `Qwen3.5-4B-Q4_K_M.gguf`.

## Arborescence

- `mcp_server/` : serveur MCP V2 et knowledge store versionne
- `schemas/` : contrats tools + schema de sortie tool call
- `knowledge/` : source unique (etat maison, alias, regles)
- `prompts/` : prompt system court et strict
- `benchmarks/` : cas V2 + runner + reports JSON
- `logs/` : logs serveur et traces benchmark

## Objectif V2

- Frontieres strictes entre tools
- Zero invention d'args et d'entites
- Scope global explicite (`args:{}` => all quand applicable)
- Knowledge dynamique via tools internes:
  - `get_current_knowledge()`
  - `upsert_home_entity(...)`
- Benchmark parser centre sur:
  - tool correct
  - args exacts
  - ordre multi-intent
  - no extra args / no hallucination

## Prerequis

- Python 3.10+
- `llama-server.exe` disponible (llama.cpp recent)
- Modele GGUF present, ex:
  - `D:/PROG/TEST/SMART_HOME/gguf_models/Qwen3.5-4B-Q4_K_M.gguf`

## Installation rapide

```bash
pip install -r SMART_HOME_V2/requirements.txt
```

## Lancer le serveur MCP V2

```bash
python SMART_HOME_V2/mcp_server/server.py
```

## Lancer le benchmark V2

```bash
python SMART_HOME_V2/benchmarks/run_benchmark_v2.py ^
  --model "D:/PROG/TEST/SMART_HOME/gguf_models/Qwen3.5-4B-Q4_K_M.gguf" ^
  --llama-bin "D:/PROG/TEST/SMART_HOME/llama-b8184-bin" ^
  --output "SMART_HOME_V2/benchmarks/reports/benchmark_v2_report.json"
```

Modes benchmark:

- `--benchmark-mode stateless` (defaut): comparaison stricte qualite parser
- `--benchmark-mode prod-like`: session chaude type production (latence percue)

Exemple prod-like avec serveur deja lance:

```bash
python SMART_HOME_V2/benchmarks/run_benchmark_v2.py ^
  --no-start-server --host 127.0.0.1 --port 8083 ^
  --benchmark-mode prod-like --slot-id 0 --cache-prompt-hint ^
  --n-ctx 1024 --max-tokens 64 --temperature 0 --top-p 0.9 ^
  --limit 10 ^
  --output "SMART_HOME_V2/benchmarks/reports/benchmark_v2_report_prod_like.json"
```

Option avancee de latence:

- `--prod-like-user-only`: n'envoie que le message user apres warmup  
  (peut etre plus rapide, mais peut casser la qualite parser selon modele/runtime)

## Workflow recommande

1. Executer benchmark V2 complet
2. Trier les 20 pires echecs (`worst_failures` du report)
3. Corriger d'abord:
   - descriptions tools
   - regles ambiguite
   - alias knowledge
4. Re-lancer benchmark
5. Refaire la boucle jusqu'a stabilisation categorie par categorie

## Notes Git (rigueur)

- Travailler sur une branche dediee (`feature/smarthome-v2-bootstrap`)
- Commits courts et explicites, orientes "pourquoi"
- Eviter de melanger V1 et V2 dans le meme commit

