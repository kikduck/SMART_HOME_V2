# Guide de déploiement Smart Home V2 Admin (Ubuntu + Portainer)

Guide pas à pas pour un déploiement sur serveur Ubuntu avec Portainer.

---

## 1. Ce qu'il faut transférer sur le serveur

Transférez le dossier `SMART_HOME_V2` (voir `DEPLOY_FILES.md` pour la liste détaillée). Structure minimale :

```
SMART_HOME_V2/
├── admin/
├── knowledge/
├── prompts/
├── schemas/
├── models/              # vide, rempli par download_model.sh
├── download_model.sh
└── docker-compose.portainer.yml
```

**Modèle** : exécutez `./download_model.sh` sur le serveur pour télécharger Qwen3.5-2B-Q6_K.gguf (~1.5 GB) depuis [unsloth/Qwen3.5-2B-GGUF](https://huggingface.co/unsloth/Qwen3.5-2B-GGUF).

**Option simple** : transférez tout le projet (y compris benchmarks, logs si vous voulez garder une trace).

---

## 2. Comment transférer les fichiers

### Méthode A : SCP (depuis Windows PowerShell ou WSL)

```powershell
# Depuis votre PC (dans le dossier parent de SMART_HOME_V2)
scp -r SMART_HOME_V2 user@IP_DU_SERVEUR:/home/user/
```

Remplacez `user` par votre nom d'utilisateur Ubuntu et `IP_DU_SERVEUR` par l’IP (ex. `192.168.1.10`).

### Méthode B : Git (si le projet est sur GitHub/GitLab)

Sur le serveur Ubuntu :

```bash
cd /home/user
git clone https://github.com/VOTRE_REPO/SMART_HOME_V2.git
# ou
git clone VOTRE_URL_GIT
```

### Méthode C : WinSCP ou FileZilla (interface graphique)

1. Connectez-vous en SFTP à votre serveur
2. Glissez-déposez le dossier `SMART_HOME_V2` dans `/home/user/` (ou un autre répertoire)

---

## 3. Préparer le serveur Ubuntu

### Installer Docker (si pas déjà fait)

```bash
# Connexion SSH au serveur
ssh user@IP_DU_SERVEUR

# Installation Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Déconnectez-vous et reconnectez-vous pour que le groupe soit pris en compte
```

### Installer Portainer (si pas déjà fait)

```bash
# Créer le volume Portainer
docker volume create portainer_data

# Lancer Portainer
docker run -d -p 9000:9000 -p 9443:9443 --name portainer --restart=always \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v portainer_data:/data \
  portainer/portainer-ce:latest
```

Accès : `https://IP_DU_SERVEUR:9443` (ou `:9000` en HTTP).

---

## 4. Déployer avec Portainer

### Étape 1 : Ouvrir Portainer

1. Allez sur `https://IP_DU_SERVEUR:9443`
2. Créez un compte admin (première visite)
3. Sélectionnez **Local** (ou votre environnement Docker)

### Étape 2 : Préparer les données sur le serveur

Sur le serveur (ex. `elliot@yolo`), le projet doit être dans un dossier persistant avec le modèle :

```bash
cd /home/elliot/SMART_HOME_V2
chmod +x download_model.sh
./download_model.sh
```

Vérifiez que le chemin existe pour Docker :

```bash
docker run --rm -v /home/elliot/SMART_HOME_V2:/check alpine ls -la /check
```

Si vous voyez les dossiers `admin`, `knowledge`, `models`, etc., le chemin est accessible.

### Étape 3 : Créer la Stack (méthode recommandée : Git)

1. Menu **Stacks** → **Add stack**
2. Nom : `smarthome-admin`
3. **Build method** : **Git Repository**
4. **Repository URL** : `https://github.com/kikduck/TEST` (ou votre repo)
5. **Compose path** : `SMART_HOME_V2/docker-compose.portainer.yml`
6. **Base path** : remplacez `/home/elliot/SMART_HOME_V2` dans les volumes si votre projet est ailleurs (ex. `/home/pi/SMART_HOME_V2`)

Le compose utilise `context: .` pour le build (contexte = dossier du compose) et des volumes pointant vers `/home/elliot/SMART_HOME_V2`.

### Étape 4 : Alternative – Web editor (si Git ne convient pas)

1. **Build method** : **Web editor**
2. Collez le contenu de `docker-compose.portainer.yml`
3. **Important** : remplacez `/home/elliot/SMART_HOME_V2` par votre chemin réel dans chaque volume du compose

⚠️ **Erreur "path not found"** : Portainer/Docker ne voit parfois pas le chemin du host. Dans ce cas, utilisez la méthode **Git** (étape 3).

### Étape 6 : Build et déploiement

1. Cliquez sur **Deploy the stack**
2. Portainer va construire l’image puis lancer le conteneur (quelques minutes la première fois)
3. En cas d’erreur, vérifiez les **Logs** du conteneur

### Étape 7 : Vérifier

- Ouvrez `http://IP_DU_SERVEUR:8000` dans un navigateur (depuis votre PC, téléphone ou Raspberry Pi sur le même réseau)
- L’interface Admin doit s’afficher
- **Paramètres** : sélectionnez le modèle (Qwen3.5-2B-Q6_K) et enregistrez

---

## 5. Chemins à adapter

Si votre projet est dans un autre dossier, modifiez les chemins dans le compose :

| Chemin dans l’exemple | À remplacer par |
|-----------------------|-----------------|
| `/home/elliot/SMART_HOME_V2` | Chemin réel sur votre serveur |

Pour connaître le chemin exact :

```bash
cd /chemin/vers/SMART_HOME_V2
pwd
```

Utilisez la sortie de `pwd` dans le docker-compose.

---

## 6. Stack complète (Admin + LLM)

Le `docker-compose.portainer.yml` inclut **deux services** :
- **llama** : modèle Qwen3.5-2B-Q6_K (image officielle llama.cpp)
- **admin** : interface + API /api/parse

**Activer la stack** = tout démarre. **Désactiver** = tout s’arrête.

**Prérequis** : exécuter `./download_model.sh` une fois pour télécharger le modèle (~1.5 GB) dans `models/`.

---

## 7. Dépannage

### Erreur "path ... not found" ou "unable to prepare context"

Portainer envoie le chemin de build au daemon Docker. Si le chemin n'est pas trouvé :

1. **Utilisez la méthode Git** : Stacks → Add stack → Build method: **Git Repository**
   - URL : `https://github.com/kikduck/TEST`
   - Compose path : `SMART_HOME_V2/docker-compose.portainer.yml`
   - Le build se fait depuis le clone (contexte `.`), les volumes pointent vers votre chemin local (ex. `/home/elliot/SMART_HOME_V2`).

2. **Vérifiez l'accès au chemin** sur le host :
   ```bash
   docker run --rm -v /home/elliot/SMART_HOME_V2:/check alpine ls /check
   ```
   Si ça échoue, le daemon Docker n'a pas accès à ce chemin.

3. **Adaptez les chemins** dans les volumes du compose si votre projet est ailleurs (ex. `/home/pi/SMART_HOME_V2`).

### Erreur "context not found" ou "path does not exist"

- Le `context` du build doit pointer vers le dossier `SMART_HOME_V2`
- Avec la méthode Git, `context: .` suffit (le compose est dans `SMART_HOME_V2/`)

### Erreur "port 8000 already in use"

- Un autre service utilise le port 8000
- Changez `8000:8000` en `8080:8000` (ou un autre port libre) pour exposer l’admin sur le port 8080

### L’admin ne répond pas

- Vérifiez que le conteneur est **Running** dans Portainer
- Consultez les **Logs** du conteneur
- Vérifiez le pare-feu : `sudo ufw allow 8000` puis `sudo ufw reload`

### Modifications non sauvegardées

- Les volumes doivent monter `knowledge`, `schemas`, `prompts`
- Vérifiez que les chemins des volumes correspondent bien aux dossiers du projet

---

## 8. API Parse (voice-to-text → tool calls)

Une fois l’Admin et le llama-server déployés, envoyez une instruction depuis votre téléphone, Raspberry Pi ou tout client HTTP :

```http
POST http://IP_SERVEUR:8000/api/parse
Content-Type: application/json

{"text": "allume le salon"}
```

**Réponse :**
```json
{
  "parsed": [
    {"tool": "set_lighting", "args": {"room": "salon"}}
  ],
  "raw": "{\"tool\":\"set_lighting\",\"args\":{\"room\":\"salon\"}}",
  "wall_ms": 3200
}
```

**Exemples de requêtes :**
- `{"text": "éteints la cuisine et allume le salon"}` → 2 tool calls
- `{"text": "mets 21 degrés dans la chambre"}` → set_temperature
- `{"text": "mode nuit"}` → set_global_preset

**Prérequis :** le llama-server doit tourner (port 8085 par défaut). Configurez `llama_base_url` dans Paramètres si le serveur est sur une autre machine (ex. `http://192.168.1.10:8085`).

---

## 9. Mise à jour après modification du code

1. Dans Portainer : **Stacks** → `smarthome-admin` → **Editor**
2. Cliquez sur **Update the stack**
3. Ou, si vous avez transféré de nouveaux fichiers : **Recreate** le conteneur (Portainer reconstruira l’image)

---

## Résumé rapide

1. Transférer `SMART_HOME_V2` sur le serveur (SCP, Git ou SFTP)
2. Installer Docker + Portainer si nécessaire
3. Dans Portainer : **Stacks** → **Add stack** → coller le docker-compose avec les bons chemins
4. **Deploy the stack**
5. Accéder à l’admin sur `http://IP_SERVEUR:8000`

---

## Checklist avant déploiement

- [ ] Dossier `SMART_HOME_V2` transféré sur le serveur
- [ ] Chemins dans le docker-compose adaptés (`/home/user/` → votre chemin)
- [ ] Port 8000 libre (ou modifié dans le compose)
- [ ] Docker et Portainer installés et fonctionnels
