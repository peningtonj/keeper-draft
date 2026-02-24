# Keeper League Draft Board

Draft board web app for a super coach keeper league. It loads player data from the local SuperCoach player list in server/players.json, then lets you filter available players by position and review basic SuperCoach metrics. Player data is cached locally and can be refreshed with an update button.

## Features
- Filter by position, team, and age categories (1st–4th year, Free Agents, Senior 30+)
- Search by player name
- Cache player data in the browser and backend
- Manual update button to refresh data

## Setup

### Frontend
1. Install dependencies: `npm install`
2. Start the app: `npm run dev`

### Backend
1. Install Python dependencies: `python -m pip install -r server/requirements.txt`
2. Start the API server: `python -m uvicorn server.app:app --reload --port 8000`

The frontend automatically proxies `/api` requests to the backend during development.

Note: Age and years played are sourced from DraftGuru playing lists and cached in server/cache/years.json for subsequent loads.
