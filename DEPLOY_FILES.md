# Fichiers à déployer sur le serveur Ubuntu

## Structure minimale à transférer

```
SMART_HOME_V2/
├── admin/
│   ├── app.py
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── requirements.txt
│   └── static/
│       ├── index.html
│       ├── style.css
│       └── app.js
├── knowledge/
│   ├── home_state.json
│   ├── aliases.json
│   ├── rules.json
│   ├── config.json
│   └── presets/
├── prompts/
│   ├── system_prompt_v2.txt
│   └── decomposer_prompt.txt
├── schemas/
│   ├── tools_contracts.json
│   └── tool_call.schema.json
├── models/                    # vide au départ, rempli par download_model.sh
├── download_model.sh
├── docker-compose.portainer.yml
└── DEPLOYMENT.md
```

## Fichiers exclus (ne pas transférer)

- `*.gguf` (modèles) : téléchargés séparément via `download_model.sh`
- `benchmarks/`, `logs/` : optionnels
- `__pycache__/`, `*.pyc`
- Fichiers de dev Windows

## Modèle recommandé

**Qwen3.5-2B-Q6_K** (1.5 GB)  
Source : https://huggingface.co/unsloth/Qwen3.5-2B-GGUF

Téléchargement : exécuter `./download_model.sh` sur le serveur.
