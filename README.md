# Meine_chatbot

Application web interne (React + FastAPI) pour interroger des documents Paperless-ngx et retourner des reponses en francais avec sources.

## Fonctionnalites

- Interface chat simple et rapide
- API FastAPI avec endpoints de sante et de conversation
- Recherche documentaire via Paperless-ngx
- Generation de reponse via Ollama
- Affichage des sources utilisees
- Deploiement complet avec Docker Compose

## Architecture

- `backend/` API FastAPI
- `frontend/` interface React (servie par Nginx en production)
- `docker-compose.yml` orchestration des services

## Prerequis

- Docker + Docker Compose
- Acces reseau vers un serveur Paperless-ngx
- Acces reseau vers un serveur Ollama

## Configuration

1. Copier le fichier d'exemple:

```bash
cp .env.example .env
```

2. Renseigner les variables dans `.env`:

- `PAPERLESS_BASE_URL`
- `PAPERLESS_TOKEN`
- `OLLAMA_BASE_URL`
- `OLLAMA_MODEL`

## Lancement (Docker)

```bash
docker compose up --build -d
```

Applications exposees:

- Frontend: [http://localhost:8080](http://localhost:8080)
- Backend: [http://localhost:8000](http://localhost:8000)

## Verification

```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/health/paperless
curl http://localhost:8000/api/health/ollama
```

## API

- `GET /api/health`
- `GET /api/health/paperless`
- `GET /api/health/ollama`
- `POST /api/chat`

Exemple:

```bash
curl -X POST "http://localhost:8000/api/chat" \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"Quelles sont les regles de validation des factures ?\"}"
```

## Developpement local

Backend:

```bash
cd backend
python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

## Contribution

Les contributions sont les bienvenues.

1. Forker le repository
2. Creer une branche de travail (`feature/ma-modification`)
3. Commiter avec un message clair
4. Ouvrir une Pull Request avec une description concise

Merci d'eviter d'inclure des secrets (tokens, URLs internes, fichiers `.env`) dans les commits.
