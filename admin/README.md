# Smart Home V2 Admin

UI d’administration pour configurer la maison, les alias, les tools, le prompt et les presets.

## Déploiement Docker (Ubuntu / Ryzen 5 Pro 2400G)

Optimisé pour un serveur léger (4 cœurs, 8 threads). Pas de build frontend, Uvicorn 1 worker.

```bash
# Depuis SMART_HOME_V2
cd SMART_HOME_V2
docker compose -f admin/docker-compose.yml up -d

# Accès: http://localhost:8000
```

Ou build manuel :

```bash
cd SMART_HOME_V2
docker build -f admin/Dockerfile -t smarthome-admin .
docker run -p 8000:8000 -v $(pwd)/knowledge:/app/knowledge -v $(pwd)/schemas:/app/schemas -v $(pwd)/prompts:/app/prompts smarthome-admin
```

## Développement local

```bash
cd SMART_HOME_V2/admin
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

## Sections de l’UI

| Onglet | Contenu |
|--------|---------|
| **Maison** | Pièces, lumières, appareils, capteurs par pièce |
| **Alias** | Alias → canonique (room, device, fixture, preset) |
| **Tools** | Éditeur JSON de `tools_contracts.json` |
| **Prompt** | Éditeur du system prompt |
| **Presets** | Presets lighting/global, import/export .json |

## Presets .json

- **Éditer** : bouton « Éditer » sur chaque preset → modal avec le contenu JSON
- Fichiers : `knowledge/presets/{scope}_{name}.json` (ex: `lighting_lecture.json`)
- Le JSON définit les paramètres pour les tools (ex: `{ "intensity": 80, "color_temp": 3000 }`)
- Import : bouton « Importer .json » pour charger un fichier preset
- Format import : `{ "scope": "lighting"|"global", "name": "cinema", ... }`
