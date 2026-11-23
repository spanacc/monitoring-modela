"""
Server dashboarda.

ŠTA RADI
--------
Mali veb server (biblioteka FastAPI) koji:
  1. pregledaču šalje stranicu dashboarda (folder static/),
  2. odgovara na pitanja te stranice (adrese koje počinju sa /api/),
  3. po želji sam pokreće krug nadzora na svakih N sekundi.

ADRESE (API)
------------
    GET  /api/stanje                       verzija podataka (stranica pita često)
    GET  /api/pregled?dana=30              stanje svih izvora
    GET  /api/serija?model=..&izvor=..     grafikoni jednog izvora
    GET  /api/alarmi?svi=false             spisak alarma
    POST /api/alarmi/{broj}/potvrdi        {"ko": "Veljko", "napomena": "..."}
    POST /api/alarmi/{broj}/resi           {"ko": "Veljko", "napomena": "..."}
    POST /api/nadzor                       jedan krug nadzora, odmah
    GET  /api/izvori                       šta se prati (iz podešavanja)
    POST /api/izvori/predlog               ubačen fajl ili {"putanja"}: šta je prepoznato
    POST /api/izvori                       dodaj izvor (potvrđen predlog) i odmah proveri
    DELETE /api/izvori/{model}             ukloni izvor i njegove podatke
    GET  /api/mejl                         podešavanja mejla (lozinka NIKAD)
    POST /api/mejl                         sačuvaj podešavanja (+ nova lozinka, ako je upisana)
    DELETE /api/mejl/lozinka               zaboravi sačuvanu lozinku
    POST /api/mejl/proba                   pošalji probni mejl odmah

DODAVANJE PODATAKA SA STRANICE (korak 7)
----------------------------------------
Fajl se šalje kao telo zahteva (bez dodatnih biblioteka), ime fajla u
zaglavlju X-Fajl. Kopira se u data/ulaz/<model>/. Podešavanja se čuvaju u
data/podesavanja.json; ta datoteka se menja samo kroz ove adrese.

BRZINA
------
Stranica na svakih 15 sekundi pita samo za verziju (nekoliko bajtova).
Ostalo traži tek kad se verzija promeni. Server pamti već izračunate
odgovore (keš) dok se verzija ne promeni, pa ni deset otvorenih
dashboarda ne opterećuje bazu deset puta više. Odgovori se šalju
sažeti (gzip).

BEZBEDNOST (osnovna; potpuna, sa prijavom, dolazi u koraku 9)
-------------------------------------------------------------
- Podrazumevano server sluša samo na 127.0.0.1: dashboard može da otvori
  samo ovaj računar, ne i drugi u mreži.
- Prihvataju se samo zahtevi upućeni na dozvoljena imena servera
  (TrustedHost). To sprečava napad "DNS rebinding", u kome tuđa stranica
  pokušava da se predstavi kao naš server.
- Svaka izmena (POST) mora da ima zaglavlje X-Dashboard. Tuđa veb stranica
  otvorena u istom pregledaču ne može da ga doda, pa ne može ni da potvrdi
  ili reši alarm u vaše ime (napad CSRF).
- Zaglavlje Content-Security-Policy: stranica sme da učita i pokrene samo
  svoje fajlove, ništa sa interneta. Zato radi i u mreži bez interneta.
- Aplikacija i dalje samo ČITA rezultate modela. Menja samo svoje alarme i
  svoja podešavanja (kad se izvor doda sa stranice).
- Adresa /api/izvori/predlog sa {"putanja"} čita fajl sa ovog računara koji
  korisnik navede. Zato dashboard mora da ostane samo za ovaj računar dok
  ne dobije prijavu (korak 9).

JEDAN PROCES ZA SVE UPISE
-------------------------
Alarme menjaju i nadzor (novi alarmi) i ljudi (potvrda, rešavanje). Kad bi
to radila dva programa u isto vreme, jedan bi mogao da pregazi izmenu
drugog. Zato je najbolje pokrenuti dashboard sa --nadzor 60: tada isti
proces radi oboje, a brava (lock) pazi da se upisi nikad ne preklope.
"""

import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

import json
import time
from urllib.parse import unquote
from zoneinfo import ZoneInfo

from app import dodavanje, tajne
from app.alarmi import mejl
from app.alarmi.evidencija import Evidencija
from app.alarmi.konfiguracija import KANAL_STRANICE, PODRAZUMEVANA_PUTANJA, Konfiguracija, MejlPodesavanja
from app.baza import Baza
from app.dashboard import podaci
from app.nadzor import jedan_krug

STATIC = Path(__file__).parent / "static"
ZAGLAVLJE_IZMENE = "X-Dashboard"  # bez njega se ništa ne menja (zaštita od CSRF)

BEZBEDNOSNA_ZAGLAVLJA = {
    # Stranica sme da koristi samo svoje fajlove: ni skripte, ni stilove,
    # ni slike sa drugih adresa. Ne sme ni da bude ugrađena u tuđu stranicu.
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


class Potvrda(BaseModel):
    ko: str = Field(min_length=1, max_length=100, pattern=r"\S")  # bar jedno slovo
    napomena: str | None = Field(default=None, max_length=500)


class ProbniProblem(BaseModel):
    vrsta: Literal["neobicna", "greska"]


class Resenje(BaseModel):
    ko: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"\S")
    napomena: str | None = Field(default=None, max_length=500)


class MejlSaStranice(MejlPodesavanja):
    # Nova lozinka: samo kad je čovek upiše. Prazno = ostaje sačuvana.
    lozinka: str | None = Field(default=None, max_length=512)


class PutanjaIzvora(BaseModel):
    putanja: str = Field(min_length=1, max_length=1000)
    model: str | None = Field(default=None, max_length=100)


class NovIzvor(BaseModel):
    putanja: str = Field(min_length=1, max_length=1000)
    model: str = Field(min_length=1, max_length=100, pattern=r"\S")
    polja: dict[str, str] = {}
    kolone: list[str] | None = None
    istorijski: bool = False
    redosled_datuma: str = Field(default="dm", pattern=r"^(dm|md)$")


class Kes:
    """Pamti izračunate odgovore dok se verzija podataka ne promeni."""

    def __init__(self, najvise: int = 64):
        self.najvise = najvise
        self.verzija: str | None = None
        self.stavke: dict = {}
        self.brava = threading.Lock()

    def uzmi(self, verzija: str, kljuc, izracunaj):
        with self.brava:
            if verzija != self.verzija:  # podaci su se promenili: sve staro je zastarelo
                self.verzija, self.stavke = verzija, {}
            if kljuc in self.stavke:
                return self.stavke[kljuc]
        vrednost = izracunaj()
        with self.brava:
            if verzija == self.verzija and len(self.stavke) < self.najvise:
                self.stavke[kljuc] = vrednost
        return vrednost


def napravi_aplikaciju(k: Konfiguracija, sada_po_podacima: bool = False,
                       nadzor_sekundi: int | None = None,
                       hostovi: list[str] | None = None,
                       putanja_podesavanja: Path = PODRAZUMEVANA_PUTANJA,
                       pre_kruga=None, izazovi_problem=None) -> FastAPI:
    """
    Pravi veb aplikaciju dashboarda.

    sada_po_podacima: "sada" je vreme poslednjeg rezultata (samo za probu
                      na simuliranim podacima, kao --sada podaci u nadzoru)
    nadzor_sekundi:   ako je zadato, krug nadzora se pokreće na toliko sekundi
    hostovi:          dozvoljena imena servera (podrazumevano samo ovaj računar)
    putanja_podesavanja: gde se čuvaju podešavanja kad se izvor doda sa stranice
    pre_kruga:        funkcija koja se pozove pre svakog kruga nadzora (probni
                      podaci "uživo" se tu dopisuju, pa nadzor nikad ne čita
                      fajl dok se u njega piše)
    izazovi_problem:  samo uz probne podatke: funkcija koja odmah dopiše jedan
                      loš rezultat (dugme "Napravi problem sada")
    """
    baza = Baza(k.baza)
    brava = threading.Lock()  # samo jedan upis u isto vreme
    kes = Kes()
    kraj_rada = threading.Event()
    nadzor = {"sekundi": nadzor_sekundi, "poslednji_krug": None, "izvestaj": None}
    izmena_podesavanja = [0]  # raste pri svakoj izmeni izvora: menja verziju (keš)

    def po_podacima() -> bool:
        """"Sada" je poslednji rezultat: za probu, ili kad su svi izvori stari podaci."""
        return sada_po_podacima or bool(k.izvori) and all(i.istorijski for i in k.izvori)

    stanje_mejla_putanja = Path(putanja_podesavanja).parent / "mejl_stanje.json"

    def stanje_mejla() -> dict:
        """Kad je poslat poslednji dnevni pregled i poslednja greška slanja (za stranicu)."""
        try:
            return json.loads(stanje_mejla_putanja.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def zapamti_stanje_mejla(**izmene) -> None:
        s = {**stanje_mejla(), **izmene}
        stanje_mejla_putanja.parent.mkdir(parents=True, exist_ok=True)
        stanje_mejla_putanja.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")

    def posalji_pregled(sada: datetime, proba: bool = False) -> None:
        """Dnevni pregled (ili probni mejl) sa trenutnim stanjem iz baze."""
        naslov, tekst, html_ = mejl.mejl_pregled(
            baza.ucitaj_alarme(), ZoneInfo(k.zona), sada, k.mejl.adresa_aplikacije,
            len(baza.modeli()), proba=proba)
        try:
            mejl.posalji_po_podesavanjima(k.mejl, naslov, tekst, html_)
        except ValueError as e:  # lozinka ne može da se dešifruje
            raise mejl.GreskaSlanja(str(e)) from None

    def dnevni_ako_treba() -> None:
        """Posle svakog kruga: ako je vreme za dnevni pregled, a danas nije poslat."""
        sada = datetime.now(timezone.utc)
        s = stanje_mejla()
        if not mejl.vreme_za_dnevni(k.mejl, sada, ZoneInfo(k.zona), s.get("dnevni")):
            return
        # Posle neuspeha ne pokušava se svakog minuta, nego na 30 minuta.
        if s.get("dnevni_neuspeh") and time.time() - s["dnevni_neuspeh"] < 1800:
            return
        try:
            posalji_pregled(sada)
            zapamti_stanje_mejla(dnevni=sada.astimezone(ZoneInfo(k.zona)).isoformat(timespec="seconds"),
                                 dnevni_neuspeh=None, greska=None)
            print(f"[{datetime.now():%H:%M:%S}] dnevni pregled poslat mejlom")
        except mejl.GreskaSlanja as e:
            zapamti_stanje_mejla(dnevni_neuspeh=time.time(), greska=f"Dnevni pregled nije poslat: {e}")
            print(f"    GREŠKA mejla: {e}")

    def krug_nadzora() -> dict:
        """Jedan krug nadzora (korak 5), pod bravom."""
        with brava:
            if pre_kruga:
                try:
                    pre_kruga()
                except Exception as e:  # probni podaci ne smeju da zaustave nadzor
                    print(f"GREŠKA probnih podataka: {e}")
            iz = jedan_krug(k, None if sada_po_podacima else datetime.now(timezone.utc))
        # Greška mejla sa stranice se pamti, da se vidi u podešavanjima.
        greske_mejla = [g for g in iz.greske if KANAL_STRANICE in g]
        if greske_mejla:
            zapamti_stanje_mejla(greska=greske_mejla[-1].split(": ", 1)[-1])
        elif iz.poslato.get(KANAL_STRANICE):
            # Slanje radi: ako je dnevni pregled ranije pao, ne čeka se 30 min.
            zapamti_stanje_mejla(greska=None, dnevni_neuspeh=None,
                                 poslednji_odmah=podaci.ms(datetime.now(timezone.utc)))
        izvestaj = {
            "novih_rezultata": iz.novih_rezultata, "provereno": iz.provereno,
            "nalaza": iz.nalaza, "novih_alarma": iz.novih_alarma,
            "otvorenih_alarma": iz.otvorenih_alarma, "greske": iz.greske,
            "poslato_mejlom": bool(iz.poslato.get(KANAL_STRANICE)),
        }
        nadzor["poslednji_krug"] = podaci.ms(datetime.now(timezone.utc))
        nadzor["izvestaj"] = izvestaj
        return izvestaj

    def petlja_nadzora() -> None:
        while not kraj_rada.is_set():
            try:
                iz = krug_nadzora()
                print(f"[{datetime.now():%H:%M:%S}] nadzor: {iz['novih_rezultata']} novih "
                      f"rezultata, {iz['novih_alarma']} novih alarma, "
                      f"{iz['otvorenih_alarma']} otvorenih")
                for greska in iz["greske"]:
                    print(f"    GREŠKA: {greska}")
            except Exception as e:  # nadzor ne sme da obori dashboard
                print(f"GREŠKA u nadzoru: {e}")
            try:
                dnevni_ako_treba()
            except Exception as e:  # ni mejl ne sme da obori dashboard
                print(f"GREŠKA dnevnog pregleda: {e}")
            kraj_rada.wait(nadzor_sekundi)

    @asynccontextmanager
    async def zivot(_app: FastAPI):
        nit = None
        if nadzor_sekundi:
            nit = threading.Thread(target=petlja_nadzora, name="nadzor", daemon=True)
            nit.start()
        yield
        kraj_rada.set()
        if nit:
            nit.join(timeout=10)

    # docs_url=None: bez automatske stranice sa opisom API-ja. Ona učitava
    # skripte sa interneta, a i ne treba da bude javno vidljiva.
    app = FastAPI(title="Monitoring modela", lifespan=zivot,
                  docs_url=None, redoc_url=None, openapi_url=None)

    def trenutna_verzija() -> str:
        v = f"{podaci.verzija(baza)}-{izmena_podesavanja[0]}"
        if not po_podacima():
            # U pravom radu vreme teče i bez novih podataka (npr. tišina
            # postaje sve duža), pa se prikaz osvežava bar na 30 s.
            v += f"-{int(datetime.now(timezone.utc).timestamp() // 30)}"
        return v

    def sada(v: str) -> datetime:
        if not po_podacima():
            return datetime.now(timezone.utc)
        return kes.uzmi(v, "sada", lambda: podaci.poslednje_vreme(baza)) or datetime.now(timezone.utc)

    # --- čitanje ---

    @app.get("/api/stanje")
    def stanje():
        return {"verzija": trenutna_verzija(), "sada_po_podacima": po_podacima(),
                "nadzor": nadzor, "izvora": len(k.izvori), "demo": bool(izazovi_problem)}

    @app.get("/api/pregled")
    def pregled(dana: float = Query(30, gt=0, le=3700)):
        v = trenutna_verzija()
        odgovor = kes.uzmi(v, ("pregled", dana), lambda: podaci.pregled(baza, k, sada(v), dana))
        return {**odgovor, "verzija": v}

    @app.get("/api/serija")
    def serija(model: str = Query(max_length=200), izvor: str = Query(max_length=200),
               dana: float = Query(30, gt=0, le=3700), velicina: str | None = None,
               horizont: int | None = None):
        v = trenutna_verzija()
        try:
            return kes.uzmi(v, ("serija", model, izvor, dana, velicina, horizont),
                            lambda: podaci.serija(baza, k, sada(v), model, izvor, dana,
                                                  velicina, horizont))
        except KeyError as e:
            raise HTTPException(404, e.args[0])

    @app.get("/api/alarmi")
    def lista_alarma(svi: bool = False):
        v = trenutna_verzija()
        return kes.uzmi(v, ("alarmi", svi), lambda: podaci.alarmi(baza, svi))

    # --- izmene (samo uz zaglavlje X-Dashboard) ---

    @app.post("/api/alarmi/{broj}/potvrdi")
    def potvrdi(broj: int, telo: Potvrda):
        with brava:
            evidencija = Evidencija(baza=baza)
            try:
                a = evidencija.potvrdi(broj, telo.ko.strip(), telo.napomena)
            except KeyError as e:
                raise HTTPException(404, e.args[0])
            evidencija.sacuvaj()
        return podaci.za_prikaz(a)

    @app.post("/api/alarmi/{broj}/resi")
    def resi(broj: int, telo: Resenje):
        with brava:
            evidencija = Evidencija(baza=baza)
            try:
                a = evidencija.resi(broj, (telo.napomena or "").strip() or None,
                                     telo.ko.strip() if telo.ko else None)
            except KeyError as e:
                raise HTTPException(404, e.args[0])
            evidencija.sacuvaj()
        return podaci.za_prikaz(a)

    @app.post("/api/nadzor")
    def nadzor_odmah():
        return krug_nadzora()

    @app.post("/api/demo/problem")
    def napravi_problem(z: ProbniProblem):
        """Probni podaci: model "odjednom" pogreši, provera odmah ide (i mejl sa njom)."""
        if not izazovi_problem:
            raise HTTPException(404, "Probni podaci nisu uključeni (python -m app --demo).")
        with brava:
            opis = izazovi_problem(z.vrsta)
        return {"opis": opis, "izvestaj": krug_nadzora()}

    # --- izvori: dodavanje podataka sa stranice ---

    # --- mejl ---

    def opis_mejla() -> dict:
        s = stanje_mejla()
        return {**k.mejl.model_dump(),
                # Lozinka se NIKAD ne šalje nazad: samo da li postoji.
                "lozinka_sacuvana": tajne.postoji("mejl"),
                "lozinka_iz_okruzenja": bool(os.environ.get(mejl.PROMENLJIVA_LOZINKE)),
                "dnevni_poslat": s.get("dnevni"), "greska": s.get("greska")}

    @app.get("/api/mejl")
    def mejl_podesavanja():
        return opis_mejla()

    @app.post("/api/mejl")
    def sacuvaj_mejl(z: MejlSaStranice):
        with brava:
            novo = MejlPodesavanja(**z.model_dump(exclude={"lozinka"}))
            if novo.ukljuceno and not (novo.server and novo.za):
                raise HTTPException(400, "Za uključivanje mejla upišite server i bar jednog primaoca.")
            if z.lozinka:
                tajne.sacuvaj("mejl", z.lozinka)
            k.mejl = novo
            k.sacuvaj(putanja_podesavanja)
            # Nova podešavanja (npr. ispravljena lozinka): dnevni pregled se
            # pokušava odmah, ne čeka se 30 minuta posle prethodnog neuspeha.
            zapamti_stanje_mejla(dnevni_neuspeh=None)
        return opis_mejla()

    @app.delete("/api/mejl/lozinka")
    def zaboravi_lozinku():
        tajne.obrisi("mejl")
        return opis_mejla()

    poslednja_proba = [0.0]

    @app.post("/api/mejl/proba")
    def probni_mejl():
        # Najviše jedan probni mejl na 10 s: dugme ne sme da postane "top za mejlove".
        if time.time() - poslednja_proba[0] < 10:
            raise HTTPException(429, "Sačekajte malo pre sledećeg probnog mejla.")
        poslednja_proba[0] = time.time()
        try:
            posalji_pregled(datetime.now(timezone.utc), proba=True)
        except mejl.GreskaSlanja as e:
            zapamti_stanje_mejla(greska=str(e))
            raise HTTPException(400, str(e))
        zapamti_stanje_mejla(greska=None, dnevni_neuspeh=None)
        return {"poruka": f"Probni mejl je poslat na: {', '.join(k.mejl.za)}."}

    @app.get("/api/izvori")
    def izvori():
        return [dodavanje.opis_izvora(i) for i in k.izvori]

    @app.post("/api/izvori/predlog")
    async def predlog_izvora(request: Request):
        """
        Telo je ili CSV fajl (zaglavlje X-Fajl = ime fajla), ili JSON
        {"putanja": "..."} za fajl ili folder koji već postoji na ovom računaru.
        """
        try:
            if request.headers.get("content-type", "").startswith("application/json"):
                z = PutanjaIzvora.model_validate(await request.json())
                putanja = dodavanje.razresi_putanju(z.putanja)
                return dodavanje.predlog(putanja, k.zona, z.model)
            ime = unquote(request.headers.get("x-fajl", "")) or "podaci.csv"
            duzina = int(request.headers.get("content-length") or 0)
            if duzina > dodavanje.NAJVECI_FAJL:
                raise ValueError(f"Fajl je veći od {dodavanje.NAJVECI_FAJL // 1024 // 1024} MB.")
            sadrzaj = await request.body()
            model = dodavanje.bezbedno_ime(ime).rsplit(".", 1)[0]
            putanja = dodavanje.sacuvaj_ubaceni_fajl(model, ime, sadrzaj)
            return dodavanje.predlog(putanja, k.zona, model)
        except (ValueError, OSError) as e:
            raise HTTPException(400, str(e))

    @app.post("/api/izvori")
    def dodaj_izvor(z: NovIzvor):
        with brava:
            try:
                izvor = dodavanje.dodaj_izvor(k, Path(z.putanja), z.model, z.polja, z.kolone,
                                              z.istorijski, z.redosled_datuma, putanja_podesavanja)
            except (ValueError, OSError) as e:
                raise HTTPException(400, str(e))
            izmena_podesavanja[0] += 1
        izvestaj = krug_nadzora()
        return {"izvor": dodavanje.opis_izvora(izvor), "izvestaj": izvestaj}

    @app.delete("/api/izvori/{model}")
    def ukloni_izvor(model: str):
        with brava:
            try:
                izvor = dodavanje.ukloni_izvor(k, model, putanja_podesavanja)
            except KeyError as e:
                raise HTTPException(404, e.args[0])
            baza.obrisi_model(model)
            izmena_podesavanja[0] += 1
        return dodavanje.opis_izvora(izvor)

    # --- zaštita i zaglavlja za sve odgovore ---

    @app.middleware("http")
    async def bezbednost(request: Request, call_next):
        if request.method not in ("GET", "HEAD") and ZAGLAVLJE_IZMENE not in request.headers:
            return JSONResponse({"detail": "Izmene su dozvoljene samo iz dashboarda."},
                                status_code=403)
        odgovor = await call_next(request)
        for ime, vrednost in BEZBEDNOSNA_ZAGLAVLJA.items():
            odgovor.headers.setdefault(ime, vrednost)
        # Podaci se ne čuvaju u kešu pregledača (uvek sveži); stranica se
        # proverava pri svakom otvaranju, ali se ne skida ponovo ako se nije menjala.
        odgovor.headers["Cache-Control"] = (
            "no-store" if request.url.path.startswith("/api/") else "no-cache")
        return odgovor

    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(TrustedHostMiddleware,
                       allowed_hosts=hostovi or ["127.0.0.1", "localhost"])

    # Sama stranica: sve ostale adrese služe fajlove iz foldera static/.
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="stranica")
    return app
