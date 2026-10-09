# Train Route Finder

A Django web app that finds train journeys between two cities. You add cities and trains, then ask for a trip from A to B. The app searches every possible connection, keeps the ones that pass through the cities you require and fit your time limit, and lists them from fastest to slowest.

## Features

- **Route search.** The rail network is modelled as a directed graph (cities are nodes, trains are edges). A depth-first search lists every path from start to destination that visits no city twice.
- **Filters.** You can require stopovers in specific cities and set a maximum total travel time.
- **Ranking.** Matching routes are sorted by total duration.
- **Saved routes.** A found journey can be stored as a named route. Saved routes can be listed and opened again.
- **Data management.** Create, view, update and delete pages for cities and trains. Validation stops a train from departing and arriving at the same city, and stops the same city and country pair from being added twice.

## Tech stack

Python · Django 3.1 · SQLite (local) · PostgreSQL-ready (`dj-database-url`, `psycopg2`) · Gunicorn · WhiteNoise

## Project structure

```
src/
├── travel/   # project settings, root URLs, search and save views
├── cities/   # City model + CRUD
├── trains/   # Train model + CRUD
└── routes/   # Route model, search form, graph search (utils.py)
```

The search logic lives in [`src/routes/utils.py`](src/routes/utils.py).

## Run locally

```bash
git clone https://github.com/selezenart/routes_api.git
cd routes_api
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cd src
python manage.py migrate
python manage.py createsuperuser   # optional, for /admin
python manage.py runserver
```

Then open http://127.0.0.1:8000. Add a few cities and trains, then search for a route.
