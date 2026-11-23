"""
Dashboard: pregled stanja svih modela u pregledaču (browseru).

    python -m app.dashboard --sada podaci     # proba na simuliranim podacima
    python -m app.dashboard --nadzor 60       # pravi rad: dashboard + nadzor na 60 s

Delovi:
    podaci.py     iz baze priprema ono što ekran prikazuje
    server.py     mali veb server (FastAPI): daje stranicu i podatke
    __main__.py   pokretanje iz Terminala
    static/       stranice (index.html, podesavanja.html), stil.css i skripte (pregled.js, podesavanja.js, alati.js)
"""
