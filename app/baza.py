"""
Baza podataka: čuva sve rezultate i sve alarme.

ZAŠTO BAZA
----------
1. Istorija ostaje. Ako model svaki dan prepisuje svoj fajl, bez baze bi
   stari rezultati nestali, a sa njima i normalni period.
2. Iz baze se čita samo ono što treba (npr. poslednjih 30 dana), pa nadzor
   ostaje brz i kad se skupe godine podataka.
3. Alarmi su na jednom mestu, odakle će ih čitati i dashboard (korak 6).

KOJA BAZA
---------
Za probu SQLite: obična datoteka (data/monitoring.db), ništa ne mora da se
instalira. Kod je pisan preko biblioteke SQLAlchemy, pa se za pravi rad
može preći na PostgreSQL (ili bazu koju IT odredi) promenom samo adrese
u konfiguraciji, npr:

    sqlite:///data/monitoring.db                      (proba)
    postgresql+psycopg://korisnik@server/monitoring   (pravi rad)

VREME
-----
Sva vremena se u bazu upisuju u UTC. SQLite inače tiho odbacuje vremensku
zonu, pa bi 14:00 po beogradskom vremenu postalo 14:00 bez zone, što je
pogrešan trenutak. Pri čitanju se zona UTC vraća.

UVOZ SAMO NOVIH REDOVA
----------------------
Svaki rezultat pamti iz kog fajla je došao i koji je po redu u njemu.
Kad se fajl ponovo pročita, upisuju se samo rezultati posle poslednjeg
već upisanog. Pretpostavka: model fajl samo DOPISUJE (nove redove na kraj).
"""

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    func,
    insert,
    or_,
    select,
)

from app.alarmi.evidencija import Alarm
from app.schema import Rezultat

meta = MetaData()

# Tabela rezultata: polja univerzalnog formata (korak 1) + odakle je red stigao.
rezultati = Table(
    "rezultati", meta,
    Column("id", Integer, primary_key=True),
    Column("izvor_fajl", String(500), nullable=False),  # iz kog fajla
    Column("red", Integer, nullable=False),  # koji je po redu u tom fajlu
    Column("vreme", DateTime(timezone=True), nullable=False),
    Column("model", String(200), nullable=False),
    Column("izvor", String(200), nullable=False),
    Column("velicina", String(200), nullable=False),
    Column("vrednost", Float),
    Column("kategorija", String(200)),
    Column("jedinica", String(50)),
    Column("horizont_min", Integer),
    Column("stvarna_vrednost", Float),
    Column("stvarna_kategorija", String(200)),
    Column("status", String(20), nullable=False),
    Column("poruka", Text),
    UniqueConstraint("izvor_fajl", "red"),  # isti red se ne upisuje dvaput
)
# Indeks = "sadržaj knjige": brzo nalaženje rezultata jednog modela u vremenskom
# opsegu, bez pregledanja cele tabele.
Index("ix_rezultati_model_vreme", rezultati.c.model, rezultati.c.vreme)

# Tabela alarma: ista polja kao klasa Alarm (korak 4).
alarmi = Table(
    "alarmi", meta,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("tip", String(50), nullable=False),
    Column("model", String(200), nullable=False),
    Column("izvor", String(200), nullable=False),
    Column("od", DateTime(timezone=True), nullable=False),
    Column("do", DateTime(timezone=True), nullable=False),
    Column("ozbiljnost", String(20), nullable=False),
    Column("opis", Text, nullable=False),
    Column("status", String(20), nullable=False),
    Column("prvi_put", DateTime(timezone=True), nullable=False),
    Column("poslednji_put", DateTime(timezone=True), nullable=False),
    Column("za_slanje", Boolean, nullable=False),
    Column("potvrdio", String(200)),
    Column("napomena", Text),
)

POLJA_REZULTATA = list(Rezultat.model_fields)
POLJA_ALARMA = list(Alarm.model_fields)
VREMENA_ALARMA = ["od", "do", "prvi_put", "poslednji_put"]


def u_utc(vreme: datetime) -> datetime:
    """Vreme za upis u bazu: uvek UTC."""
    return vreme.astimezone(timezone.utc)


def iz_baze(vreme: datetime) -> datetime:
    """Vreme pročitano iz baze: SQLite ga vrati bez zone, a znamo da je UTC."""
    return vreme.replace(tzinfo=timezone.utc) if vreme.tzinfo is None else vreme.astimezone(timezone.utc)


class Baza:
    def __init__(self, adresa: str):
        if adresa.startswith("sqlite:///"):
            # Za SQLite: napravi folder za datoteku baze, ako ne postoji.
            Path(adresa.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        self.motor = create_engine(adresa)
        meta.create_all(self.motor)  # napravi tabele, ako ne postoje

    # --- rezultati ---

    def upisi_rezultate(self, izvor_fajl: str, lista: list[Rezultat]) -> int:
        """
        Upisuje rezultate pročitane iz jednog fajla. Upisuju se samo oni koji
        su po redu posle poslednjeg već upisanog iz tog fajla. Vraća broj novih.
        """
        with self.motor.begin() as veza:  # begin = sve ili ništa (transakcija)
            vec_upisano = veza.execute(
                select(func.max(rezultati.c.red)).where(rezultati.c.izvor_fajl == izvor_fajl)
            ).scalar() or 0
            novi = []
            for red, r in enumerate(lista, start=1):
                if red > vec_upisano:
                    podaci = r.model_dump()
                    podaci["vreme"] = u_utc(r.vreme)
                    podaci["status"] = r.status.value
                    novi.append({"izvor_fajl": izvor_fajl, "red": red, **podaci})
            if novi:
                veza.execute(insert(rezultati), novi)
        return len(novi)

    def obrisi_model(self, model: str) -> None:
        """Briše sve rezultate i alarme jednog modela (kad se izvor ukloni sa dashboarda)."""
        with self.motor.begin() as veza:
            veza.execute(delete(rezultati).where(rezultati.c.model == model))
            veza.execute(delete(alarmi).where(alarmi.c.model == model))

    def fajlovi_po_modelu(self) -> dict[str, set[str]]:
        """Iz kojih fajlova su stigli rezultati svakog modela."""
        with self.motor.connect() as veza:
            redovi = veza.execute(select(rezultati.c.model, rezultati.c.izvor_fajl).distinct())
            po_modelu: dict[str, set[str]] = {}
            for model, fajl in redovi:
                po_modelu.setdefault(model, set()).add(fajl)
            return po_modelu

    def modeli(self) -> list[str]:
        with self.motor.connect() as veza:
            return list(veza.execute(select(rezultati.c.model).distinct()).scalars())

    def prvo_i_poslednje(self, model: str) -> tuple[datetime, datetime]:
        """Vreme prvog i poslednjeg rezultata modela."""
        with self.motor.connect() as veza:
            prvo, poslednje = veza.execute(
                select(func.min(rezultati.c.vreme), func.max(rezultati.c.vreme))
                .where(rezultati.c.model == model)
            ).one()
        return iz_baze(prvo), iz_baze(poslednje)

    def citaj_rezultate(self, model: str, kraj_osnove: datetime | None = None,
                        pocetak: datetime | None = None) -> list[Rezultat]:
        """
        Rezultati jednog modela, poređani po vremenu.

        Ako su zadati `kraj_osnove` i `pocetak`, čita samo normalni period
        (sve pre `kraj_osnove`) i skorašnje rezultate (sve od `pocetak`).
        Ono između se ne čita: ne treba ni za učenje granica ni za proveru,
        a tako nadzor ostaje brz i posle godina rada.
        """
        upit = select(rezultati).where(rezultati.c.model == model)
        if kraj_osnove and pocetak and pocetak > kraj_osnove:
            upit = upit.where(or_(rezultati.c.vreme < u_utc(kraj_osnove),
                                  rezultati.c.vreme >= u_utc(pocetak)))
        upit = upit.order_by(rezultati.c.vreme, rezultati.c.id)

        with self.motor.connect() as veza:
            redovi = veza.execute(upit).mappings().all()
        lista = []
        for red in redovi:
            podaci = {polje: red[polje] for polje in POLJA_REZULTATA}
            podaci["vreme"] = iz_baze(podaci["vreme"])
            lista.append(Rezultat(**podaci))
        return lista

    # --- alarmi ---

    def ucitaj_alarme(self) -> list[Alarm]:
        with self.motor.connect() as veza:
            redovi = veza.execute(select(alarmi).order_by(alarmi.c.id)).mappings().all()
        lista = []
        for red in redovi:
            podaci = dict(red)
            for polje in VREMENA_ALARMA:
                podaci[polje] = iz_baze(podaci[polje])
            lista.append(Alarm(**podaci))
        return lista

    def sacuvaj_alarme(self, lista: list[Alarm]) -> None:
        """
        Zamenjuje sve alarme u bazi. Alarma je malo (desetine, stotine), pa je
        ovo najjednostavnije, a u transakciji: ili se sve upiše, ili ništa.
        """
        redovi = []
        for a in lista:
            podaci = a.model_dump()
            for polje in VREMENA_ALARMA:
                podaci[polje] = u_utc(podaci[polje])
            podaci["ozbiljnost"] = a.ozbiljnost.value
            podaci["status"] = a.status.value
            redovi.append(podaci)
        with self.motor.begin() as veza:
            veza.execute(delete(alarmi))
            if redovi:
                veza.execute(insert(alarmi), redovi)
