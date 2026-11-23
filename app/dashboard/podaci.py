"""
Podaci za dashboard: iz baze pripremaju tačno ono što ekran prikazuje.

ŠTA JE OVO
----------
Stranica u pregledaču (browseru) ne čita bazu sama. Traži podatke od
servera (server.py), a server ih dobija odavde:

    verzija()   kratak "otisak" baze: menja se čim stigne nov rezultat
                ili se promeni neki alarm
    pregled()   stanje svih izvora, za rečenicu na vrhu i "Stanje izvora"
    serija()    sve za grafikone jednog izvora
    alarmi()    spisak alarma

Vremena se šalju kao broj milisekundi od 1.1.1970. (UTC). Tako ih
JavaScript u pregledaču direktno razume, a u lokalno vreme ih pretvara
tek kad ih ispisuje.

BRZINA
------
1. Grafikon nikad ne dobije više od NAJVISE_TACAKA tačaka. Ako ih ima
   više, svaka grupa susednih tačaka se svede na najmanju i najveću
   vrednost, pa se nagli skokovi i dalje vide. Ekran ionako nema više
   piksela od toga.
2. Za grafikon se iz baze čita samo izabrani izvor, i to samo normalni
   period i prikazani dani (isto kao u nadzoru).
3. Server pamti već izračunato dok se verzija ne promeni (vidi server.py).

ISTE GRANICE KAO NADZOR
-----------------------
Naučene granice i nemoguće vrednosti računaju se istim funkcijama kao u
nadzoru (kalibrisi, nemoguce_tacke), nad istim normalnim periodom. Zato
dashboard pokazuje tačno ono na osnovu čega alarmi nastaju, a ne neku
svoju procenu.
"""

import hashlib
import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from statistics import mean, median
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select

from app.alarmi.evidencija import REDOSLED, Alarm, StatusAlarma
from app.alarmi.konfiguracija import Konfiguracija
from app.baza import POLJA_REZULTATA, Baza, iz_baze, u_utc
from app.baza import alarmi as tabela_alarma
from app.baza import rezultati as tabela_rezultata
from app.provere import Podesavanja
from app.provere.kalibracija import kalibrisi, opisi_granice
from app.provere.kvalitet import nemoguce_tacke
from app.provere.osnova import Granice, po_serijama, prozori, trajanje
from app.provere.tacnost import greske, kategorije_tacke
from app.schema import Rezultat, Status

# Imena problema za ljude (u bazi su kratka imena). Običnim rečima, bez
# stručnih izraza: ovo čitaju i ljudi koji ne znaju šta je "drift".
NAZIVI = {
    "izostanak": "Podaci ne stižu",
    "duplikat": "Isti podaci stigli više puta",
    "greska_modela": "Model javlja grešku",
    "prazne_vrednosti": "Rezultati bez vrednosti",
    "nemoguca_vrednost": "Neobična vrednost",
    "pristrasnost": "Model stalno greši u istom smeru",
    "drift": "Ponašanje se promenilo",
    "promasen_skok": "Veliki promašaj",
    "pad_tacnosti": "Tačnost je opala",
    "promena_kategorija": "Odgovori su se promenili",
}

NAJVISE_TACAKA = 1500  # najviše tačaka u jednom grafikonu

# Šta je tačka na grafikonu (četvrti broj u svakoj tački).
OBICNA, VAN_OPSEGA, GRESKA, PRAZNO = 0, 1, 2, 3


# ---------------------------------------------------------------------------
# Pomoćne funkcije za prikaz
# ---------------------------------------------------------------------------


def ms(t: datetime) -> int:
    """Vreme kao milisekunde od 1.1.1970. UTC (tako vreme čita JavaScript)."""
    return round(t.timestamp() * 1000)


def sr_broj(x: float, znak: bool = False, kao: float | None = None) -> str:
    """
    Broj u srpskom zapisu: 1234.6 -> '1.235', 63.46 -> '63,5', 0.53 -> '0,53'.
    Broj decimala zavisi od veličine broja (oko tri cifre), ili od broja
    `kao`, kad dva broja treba da se ispišu jednako precizno.
    """
    a = abs(kao if kao is not None else x)
    decimala = 0 if a >= 100 or a == 0 else 1 if a >= 1 else 2 if a >= 0.1 else 3
    if round(x, decimala) == 0:
        x, znak = 0.0, False  # bez "-0,0" i "+0,0"
    tekst = f"{x:{'+' if znak else ''},.{decimala}f}"
    tekst = tekst.replace(",", " ").replace(".", ",").replace(" ", ".")
    return tekst.replace("-", "\u2212")  # pravi znak minus, ne crtica


def ceo_broj(n: int) -> str:
    """12345 -> '12.345'."""
    return f"{n:,}".replace(",", ".")


def sa_jedinicom(x: float, jedinica: str | None, znak: bool = False,
                 kao: float | None = None) -> str:
    return sr_broj(x, znak, kao) + (f" {jedinica}" if jedinica else "")


def procenat(udeo: float) -> str:
    return f"{udeo * 100:.0f}%"


def lokalno(t: datetime, zona: ZoneInfo) -> str:
    """Vreme za čoveka, po lokalnom vremenu: '26.10. 14:00'."""
    return f"{t.astimezone(zona):%d.%m. %H:%M}"


def starost(sekundi: float) -> str:
    """Koliko je nešto staro, rečima: 'pre 4 min', 'pre 3 h', 'pre 2 dana'."""
    if sekundi < 90:
        return "upravo"
    if sekundi < 3600:
        return f"pre {round(sekundi / 60)} min"
    if sekundi < 48 * 3600:
        return f"pre {round(sekundi / 3600)} h"
    return f"pre {round(sekundi / 86400)} dana"


def prirodno(tekst: str) -> list:
    """Ključ za prirodan redosled: 'M2' pre 'M10' (a ne posle, kao u rečniku)."""
    return [int(d) if d.isdigit() else d.lower() for d in re.split(r"(\d+)", tekst)]


def ponoci(od: datetime, do: datetime, zona: ZoneInfo) -> list[datetime]:
    """Lokalne ponoći između `od` i `do`. Od njih se crtaju podeoci po danima."""
    dan = od.astimezone(zona).date() + timedelta(days=1)
    kraj = do.astimezone(zona).date()
    lista = []
    while dan <= kraj:
        lista.append(datetime.combine(dan, time(0), tzinfo=zona))
        dan += timedelta(days=1)
    return lista


def granice_dana(dan: date, zona: ZoneInfo, od: datetime, do: datetime) -> tuple[datetime, datetime]:
    """Početak i kraj lokalnog dana, skraćeni na prikazani period."""
    pocetak = datetime.combine(dan, time(0), tzinfo=zona)
    kraj = datetime.combine(dan + timedelta(days=1), time(0), tzinfo=zona)
    return max(pocetak, od), min(kraj, do)


# ---------------------------------------------------------------------------
# Verzija i "sada"
# ---------------------------------------------------------------------------


def verzija(baza: Baza) -> str:
    """
    Kratak otisak stanja baze. Menja se kad stigne nov rezultat (raste
    najveći broj reda) ili kad se bilo šta promeni na nekom alarmu.
    Stranica često pita samo za ovo, a sve ostalo traži tek kad se promeni.
    """
    a = tabela_alarma
    with baza.motor.connect() as veza:
        poslednji_red = veza.execute(select(func.max(tabela_rezultata.c.id))).scalar() or 0
        alarmi_ = veza.execute(
            select(a.c.id, a.c.status, a.c.ozbiljnost, a.c.do, a.c.poslednji_put,
                   a.c.potvrdio, a.c.napomena).order_by(a.c.id)
        ).all()
    otisak = hashlib.sha256(repr(alarmi_).encode()).hexdigest()[:12]
    return f"{poslednji_red}-{otisak}"


def poslednje_vreme(baza: Baza) -> datetime | None:
    """Vreme najnovijeg rezultata u bazi. Koristi se kao "sada" za simulirane podatke."""
    with baza.motor.connect() as veza:
        t = veza.execute(select(func.max(tabela_rezultata.c.vreme))).scalar()
    return iz_baze(t) if t else None


# ---------------------------------------------------------------------------
# Alarmi
# ---------------------------------------------------------------------------


def hitnost(a: Alarm) -> tuple:
    """
    Redosled po važnosti: nerešeni pre rešenih, ozbiljniji pre blažih,
    nepotvrđeni pre potvrđenih (na njih još niko nije reagovao), noviji
    pre starijih.
    """
    return (a.status == StatusAlarma.RESEN, -REDOSLED[a.ozbiljnost],
            a.status == StatusAlarma.POTVRDJEN, -a.do.timestamp())


def kljuc_grupe(a: Alarm) -> tuple:
    """
    Isti problem u isto vreme na više izvora jednog modela je jedan problem.
    Npr. kad svi senzori iz jedne tabele zaćute isti minut, to je jedan
    nestanak podataka, a ne osam. Takvi alarmi se broje i prikazuju zajedno.
    """
    return (a.tip, a.model, a.od, a.do, a.ozbiljnost, a.status)


def za_prikaz(a: Alarm) -> dict:
    return {
        "id": a.id, "tip": a.tip, "naziv": NAZIVI.get(a.tip, a.tip),
        "model": a.model, "izvor": a.izvor,
        "od": ms(a.od), "do": ms(a.do),
        "ozbiljnost": a.ozbiljnost.value, "status": a.status.value,
        "opis": a.opis,
        "prvi_put": ms(a.prvi_put), "poslednji_put": ms(a.poslednji_put),
        "potvrdio": a.potvrdio, "napomena": a.napomena,
    }


def alarmi(baza: Baza, svi: bool = False) -> list[dict]:
    """Nerešeni alarmi (ili svi), najvažniji prvi."""
    lista = baza.ucitaj_alarme()
    if not svi:
        lista = [a for a in lista if a.status != StatusAlarma.RESEN]
    return [za_prikaz(a) for a in sorted(lista, key=hitnost)]


# ---------------------------------------------------------------------------
# Pregled svih izvora
# ---------------------------------------------------------------------------


def pregled(baza: Baza, k: Konfiguracija, sada: datetime, dana: float) -> dict:
    """
    Stanje svih izvora za poslednjih `dana` dana: poslednji rezultat i
    koliko je star, najgori nerešen alarm i svi alarmi u tom periodu (od
    njih stranica crta traku "Stanje izvora").
    """
    zona = ZoneInfo(k.zona)

    # Poslednji rezultat svakog izvora, jednim upitom: prvo se za svaki
    # izvor nađe najnovije vreme, pa se uzme red sa baš tim vremenom.
    r = tabela_rezultata
    zbir = (select(r.c.model, r.c.izvor,
                   func.min(r.c.vreme).label("prvo"),
                   func.max(r.c.vreme).label("poslednje"))
            .group_by(r.c.model, r.c.izvor).subquery())
    upit = (select(r.c.model, r.c.izvor, r.c.vreme, r.c.velicina, r.c.jedinica,
                   r.c.horizont_min, r.c.vrednost, r.c.kategorija, r.c.status, zbir.c.prvo)
            .join(zbir, and_(r.c.model == zbir.c.model, r.c.izvor == zbir.c.izvor,
                             r.c.vreme == zbir.c.poslednje))
            .order_by(r.c.id))
    with baza.motor.connect() as veza:
        redovi = veza.execute(upit).mappings().all()

    poslednji = {}
    for red in redovi:  # ako ih ima više u istom trenutku, važi poslednji upisan
        poslednji[(red["model"], red["izvor"])] = red

    # Za stare podatke (proba, arhiva) starost se ne računa od pravog "sada",
    # nego od poslednjeg rezultata tog modela: inače bi sve bilo "pre 14 godina".
    istorijski = k.istorijski_modeli()
    kraj_modela = defaultdict(lambda: sada)
    for (model, _), red in poslednji.items():
        if model in istorijski:
            kraj_modela[model] = max(kraj_modela.get(model, iz_baze(red["vreme"])), iz_baze(red["vreme"]))

    # Prikazuje se poslednjih `dana` dana, ali ne pre prvog rezultata: kad
    # podaci traju samo nekoliko sati (npr. merenja svake sekunde), prikaz
    # se "zumira" na njih, umesto da budu tanka crta na kraju sedam dana.
    od = sada - timedelta(days=dana)
    if poslednji:
        od = max(od, min(iz_baze(red["prvo"]) for red in poslednji.values()))

    svi_alarmi = baza.ucitaj_alarme()
    po_izvoru = defaultdict(list)
    for a in svi_alarmi:
        po_izvoru[(a.model, a.izvor)].append(a)

    # Svaki model ima svoj prikazani period: stari podaci iz 2012. i stari
    # podaci iz 2020. ne mogu na istu osu, a ni stari i današnji.
    prvo_modela = {}
    for (model, _), red in poslednji.items():
        prvo_modela[model] = min(prvo_modela.get(model, iz_baze(red["prvo"])), iz_baze(red["prvo"]))
    period_modela = {m: (max(kraj_modela[m] - timedelta(days=dana), prvo_modela[m]), kraj_modela[m])
                     for m in prvo_modela}

    modeli = defaultdict(list)
    for (model, izvor), red in poslednji.items():
        njegovi = po_izvoru[(model, izvor)]
        od_m, sada_m = period_modela[model]
        aktivni = [a for a in njegovi if a.status != StatusAlarma.RESEN]
        najgori = max(aktivni, key=lambda a: REDOSLED[a.ozbiljnost], default=None)
        vreme = iz_baze(red["vreme"])
        modeli[model].append({
            "izvor": izvor,
            "istorijski": model in istorijski,
            "velicina": red["velicina"],
            "jedinica": red["jedinica"],
            "horizont_min": red["horizont_min"],
            "prvo": ms(iz_baze(red["prvo"])),
            "poslednje": ms(vreme),
            "starost_s": max((kraj_modela[model] - vreme).total_seconds(), 0),
            "vrednost": red["vrednost"],
            "kategorija": red["kategorija"],
            "greska": red["status"] == Status.GRESKA.value,
            "stanje": najgori.ozbiljnost.value if najgori else "ok",
            # Svi najgori alarmi su potvrđeni: neko već radi na tome.
            "potvrdjeno": bool(najgori) and all(
                a.status == StatusAlarma.POTVRDJEN for a in aktivni
                if a.ozbiljnost == najgori.ozbiljnost),
            # Alarmi u prikazanom periodu: [broj, tip, ozbiljnost, od, do, status]
            "alarmi": [[a.id, a.tip, a.ozbiljnost.value, ms(a.od), ms(a.do), a.status.value]
                       for a in njegovi if a.do >= od_m and a.od <= sada_m],
        })

    aktivni = [a for a in svi_alarmi if a.status != StatusAlarma.RESEN]
    grupe: dict[tuple, list[Alarm]] = defaultdict(list)
    for a in aktivni:
        grupe[kljuc_grupe(a)].append(a)
    problemi = [g[0] for g in grupe.values()]  # jedan po grupi
    ukupno = {o.value: sum(a.ozbiljnost == o for a in problemi) for o in REDOSLED}
    ukupno["nepotvrdjeno"] = sum(a.status == StatusAlarma.OTVOREN for a in problemi)
    ukupno["izvora"] = len(poslednji)
    ukupno["modela"] = len(modeli)
    najhitniji = min(aktivni, key=hitnost, default=None)

    return {
        "sada": ms(sada),
        "od": ms(od),
        "zona": k.zona,
        "dani": [ms(t) for t in ponoci(od, sada, zona)],
        "ukupno": ukupno,
        "najhitniji": za_prikaz(najhitniji) if najhitniji else None,
        "najhitniji_izvora": len(grupe[kljuc_grupe(najhitniji)]) if najhitniji else 0,
        "nazivi": NAZIVI,
        "modeli": [{"model": m, "istorijski": m in istorijski,
                    "od": ms(period_modela[m][0]), "sada": ms(period_modela[m][1]),
                    "dani": [ms(t) for t in ponoci(period_modela[m][0], period_modela[m][1], zona)],
                    "izvori": sorted(izvori, key=lambda x: prirodno(x["izvor"]))}
                   for m, izvori in sorted(modeli.items(), key=lambda par: prirodno(par[0]))],
    }


# ---------------------------------------------------------------------------
# Jedan izvor: grafikoni, pokazatelji, naučene granice
# ---------------------------------------------------------------------------


def citaj_izvor(baza: Baza, model: str, izvor: str, od: datetime,
                dana_osnove: float | None) -> list[Rezultat]:
    """
    Rezultati jednog izvora: normalni period i prikazani dani. Ono između
    se ne čita (kao u nadzoru), jer ne treba ni za granice ni za prikaz.
    """
    r = tabela_rezultata
    uslov = and_(r.c.model == model, r.c.izvor == izvor)
    with baza.motor.connect() as veza:
        prvo = veza.execute(select(func.min(r.c.vreme)).where(uslov)).scalar()
        if prvo is None:
            return []
        upit = select(r).where(uslov)
        if dana_osnove:
            kraj_osnove = iz_baze(prvo) + timedelta(days=dana_osnove)
            if od > kraj_osnove:
                upit = upit.where(or_(r.c.vreme < u_utc(kraj_osnove), r.c.vreme >= u_utc(od)))
        redovi = veza.execute(upit.order_by(r.c.vreme, r.c.id)).mappings().all()

    lista = []
    for red in redovi:
        podaci = {polje: red[polje] for polje in POLJA_REZULTATA}
        podaci["vreme"] = iz_baze(podaci["vreme"])
        lista.append(Rezultat(**podaci))
    return lista


def izaberi(serije: dict, velicina: str | None, horizont: int | None) -> tuple:
    """
    Izvor može imati više serija (npr. prognozu za 1 h i za 24 h unapred).
    Vraća traženu, a ako nije tražena nijedna, onu sa najviše rezultata.
    """
    if velicina is None:
        return max(serije, key=lambda kljuc: len(serije[kljuc]))
    for kljuc in serije:
        if kljuc[2] == velicina and kljuc[3] == horizont:
            return kljuc
    raise KeyError(f"Nema serije '{velicina}' sa horizontom {horizont}.")


def serija(baza: Baza, k: Konfiguracija, sada: datetime, model: str, izvor: str,
           dana: float, velicina: str | None = None, horizont: int | None = None) -> dict:
    """Sve što treba za prikaz jednog izvora u poslednjih `dana` dana."""
    zona = ZoneInfo(k.zona)
    p = k.podesavanja_za(model)
    if model in k.istorijski_modeli():
        # Stari podaci: "sada" je poslednji rezultat ovog modela (vidi pregled).
        poslednje = baza.prvo_i_poslednje(model)[1]
        sada = min(sada, poslednje) if poslednje else sada
    od = sada - timedelta(days=dana)

    sve = citaj_izvor(baza, model, izvor, od, p.dana_osnove)
    if not sve:
        raise KeyError(f"Nema rezultata za {model} / {izvor}.")
    serije = po_serijama(sve)
    kljuc = izaberi(serije, velicina, horizont)
    s = serije[kljuc]

    g = kalibrisi(s, p)  # iste granice kao u nadzoru
    van = nemoguce_tacke(s, g) if g else {}
    od = max(od, s[0].vreme)  # ne pre prvog rezultata (vidi pregled)
    prikaz = [x for x in s if x.vreme >= od]
    do = max(sada, s[-1].vreme)
    kategorije = any(x.kategorija is not None for x in s)

    odgovor = {
        "model": model,
        "izvor": izvor,
        "velicina": kljuc[2],
        "horizont_min": kljuc[3],
        "jedinica": s[-1].jedinica,
        "vrsta": "kategorija" if kategorije else "broj",
        "korak_s": g.korak.total_seconds() if g else None,  # koliko često stižu rezultati
        "ostale": [{"velicina": kl[2], "horizont_min": kl[3]}
                   for kl in sorted(serije, key=str) if kl != kljuc],
        "od": ms(od),
        "do": ms(do),
        "dani": [ms(t) for t in ponoci(od, do, zona)],
        "normalni_period": {"od": ms(s[0].vreme), "do": ms(g.kraj_osnove)} if g else None,
        "alarmi": [za_prikaz(a) for a in sorted(baza.ucitaj_alarme(), key=hitnost)
                   if (a.model, a.izvor) == (model, izvor) and a.do >= od and a.od <= do],
        "pokazatelji": pokazatelji(s, prikaz, g, p, van, sada, zona, model in k.istorijski_modeli()),
        "naucene_granice": naucene_granice(s, g, zona) if g else [],
        "dnevno": dnevno(s, prikaz, g, van, od, do, zona),
        "normalni_opseg": normalni_opseg(s, g, van),
    }
    odgovor["odstupanje"] = odstupanje(odgovor["dnevno"])
    if kategorije:
        odgovor["kategorije"] = kategorije_po_danu(prikaz, od, do, zona)
    else:
        odgovor["tacke"], odgovor["prekid_ms"] = tacke_grafikona(prikaz, van, g)
    return odgovor


def tacke_grafikona(prikaz: list[Rezultat], van: dict, g: Granice | None) -> tuple[list, float | None]:
    """
    Tačke za grafikon: [vreme, vrednost modela, stvarna vrednost, oznaka].
    Oznaka kaže da li je tačka posebna (nemoguća vrednost, greška, prazno).

    Vraća i razmak (ms) posle kog se linija prekida: tamo gde rezultati
    nisu stizali, linija ne sme da spoji dve udaljene tačke kao da je sve
    bilo u redu.
    """
    tacke = []
    for x in prikaz:
        if x.status == Status.GRESKA:
            oznaka = GRESKA
        elif x.vrednost is None:
            oznaka = PRAZNO
        elif x.vreme in van:
            oznaka = VAN_OPSEGA
        else:
            oznaka = OBICNA
        tacke.append([ms(x.vreme), x.vrednost, x.stvarna_vrednost, oznaka])

    tacke, grupa = proredi(tacke, NAJVISE_TACAKA)
    prekid = 2.5 * g.korak.total_seconds() * 1000 * grupa if g else None
    return tacke, prekid


def proredi(tacke: list, najvise: int) -> tuple[list, int]:
    """
    Ako tačaka ima više od `najvise`, deli ih u grupe susednih i iz svake
    zadržava najmanju i najveću vrednost, plus prvu posebnu tačku. Tako
    grafikon izgleda isto kao sa svim tačkama: skokovi i rupe se i dalje
    vide. Vraća i koliko je tačaka bilo u jednoj grupi.
    """
    if len(tacke) <= najvise:
        return tacke, 1
    grupa = math.ceil(len(tacke) / (najvise // 3))
    izabrane = []
    for i in range(0, len(tacke), grupa):
        deo = tacke[i:i + grupa]
        obicne = [t for t in deo if t[3] == OBICNA]
        posebne = [t for t in deo if t[3] != OBICNA]
        izbor = []
        if obicne:
            izbor += [min(obicne, key=lambda t: t[1]), max(obicne, key=lambda t: t[1])]
        if posebne:
            izbor.append(posebne[0])
        jedinstvene = {id(t): t for t in izbor}.values()
        izabrane += sorted(jedinstvene, key=lambda t: t[0])
    return izabrane, grupa


def kategorije_po_danu(prikaz: list[Rezultat], od: datetime, do: datetime,
                       zona: ZoneInfo, najvise: int = 3) -> dict:
    """
    Šta model vraća, po danima: koliko puta je vratio koju kategoriju.
    Radi i bez stvarnih vrednosti: ako se odnos kategorija promeni, vidi se.
    Najčešće `najvise` kategorije su posebno, ostale zajedno kao "ostalo".
    """
    ukupno = Counter(x.kategorija for x in prikaz if x.kategorija is not None)
    glavne = [kat for kat, _ in ukupno.most_common(najvise)]
    imena = glavne + (["ostalo"] if len(ukupno) > najvise else [])

    po_danu: dict[date, Counter] = defaultdict(Counter)
    for x in prikaz:
        if x.kategorija is not None:
            ime = x.kategorija if x.kategorija in glavne else "ostalo"
            po_danu[x.vreme.astimezone(zona).date()][ime] += 1

    dani = []
    for dan in sorted(po_danu):
        pocetak, kraj = granice_dana(dan, zona, od, do)
        dani.append([ms(pocetak), ms(kraj), [po_danu[dan][ime] for ime in imena]])
    return {"imena": imena, "dani": dani}


def dnevno(s: list[Rezultat], prikaz: list[Rezultat], g: Granice | None, van: dict,
           od: datetime, do: datetime, zona: ZoneInfo) -> dict | None:
    """
    Broj po danu koji prati provera drifta (ili pada tačnosti), zajedno sa
    normalnim nivoom i granicom za alarm, naučenim iz normalnog perioda.

    Provera radi sa prozorima od po `g.prozor` rezultata (otprilike dan),
    a ovde su kalendarski dani. Zato je ovo približna slika onoga što
    provera vidi, ali računata na isti način i sa istim granicama.
    """
    if g is None:
        return None
    iskljuci = set(van)
    gore = dole = None

    if any(x.kategorija is not None for x in s):
        tacke = kategorije_tacke(prikaz)
        if not tacke:
            return None  # stvarne kategorije nisu poznate
        racunaj = lambda xs: 1 - mean(xs)  # noqa: E731
        naziv, jedinica, je_procenat = "Tačnost po danu", None, True
        opis = "Koliki deo kategorija je model pogodio. Ovo prati provera pada tačnosti."
        normalno = 1 - g.stopa_gresaka if g.stopa_gresaka is not None else None
        if normalno is not None:
            dole = normalno - g.dozvoljen_rast_stope
    else:
        jedinica, je_procenat = s[0].jedinica, False
        if g.drift_po_greski:
            tacke = [(t, abs(e)) for t, e in greske(prikaz, iskljuci)]
            racunaj = median
            naziv = "Tipična greška po danu"
            opis = "Za svaki dan: tipična (srednja) veličina greške. Ovo prati provera drifta."
        else:
            tacke = [(x.vreme, x.vrednost) for x in prikaz
                     if x.vrednost is not None and x.vreme not in iskljuci]
            racunaj = mean
            naziv = "Prosečna vrednost po danu"
            opis = ("Stvarne vrednosti nisu poznate, pa provera drifta prati "
                    "same vrednosti koje model vraća.")
        normalno = g.drift_sredina
        if normalno is not None:
            gore = normalno + g.drift_dozvoljeno
            if not g.drift_po_greski:  # vrednost sme da se pomeri u oba smera
                dole = normalno - g.drift_dozvoljeno

    dani = []
    po_prozoru = g.prozor * g.korak < timedelta(days=1)
    if po_prozoru:
        # Česta merenja: prozor je kraći od dana (npr. 10 sekundi). Tada je
        # svaka tačka jedan prozor, baš onakav kakav gleda provera.
        for deo in prozori(tacke, g.prozor):
            dani.append([ms(deo[0][0]), ms(deo[-1][0] + g.korak),
                         racunaj([x for _, x in deo]), len(deo)])
        naziv = naziv.replace("po danu", f"po prozoru od {trajanje(g.prozor * g.korak)}")
    else:
        po_danu: dict[date, list] = defaultdict(list)
        for t, x in tacke:
            po_danu[t.astimezone(zona).date()].append(x)
        for dan in sorted(po_danu):
            pocetak, kraj = granice_dana(dan, zona, od, do)
            dani.append([ms(pocetak), ms(kraj), racunaj(po_danu[dan]), len(po_danu[dan])])

    if normalno is None:
        opis += (" Granica još nije naučena: u normalnom periodu ima premalo "
                 "rezultata za ovaj izvor.")
    return {"naziv": naziv, "opis": opis, "jedinica": jedinica, "procenat": je_procenat,
            "po_prozoru": po_prozoru, "normalno": normalno, "gore": gore, "dole": dole,
            "dani": dani}


def normalni_opseg(s: list[Rezultat], g: Granice | None, van: dict) -> list[float] | None:
    """
    Između kojih vrednosti se model obično kreće: od 2. do 98. percentila
    vrednosti iz normalnog perioda. Na grafikonu je to zeleni pojas, a u
    opisu problema "obično vraća između A i B".
    """
    if g is None:
        return None
    vrednosti = sorted(x.vrednost for x in s
                       if x.vreme <= g.kraj_osnove and x.vrednost is not None and x.vreme not in van)
    if len(vrednosti) < 10:
        return None
    uzmi = lambda q: vrednosti[min(len(vrednosti) - 1, round(q * (len(vrednosti) - 1)))]  # noqa: E731
    return [uzmi(0.02), uzmi(0.98)]


def odstupanje(dn: dict | None) -> dict | None:
    """
    Koliko se model udaljio od normalnog, kao procenat dozvoljenog:
    0% je tačno kao u normalnom periodu, 100% je granica posle koje se javlja
    problem. Gleda se broj koji prati provera (prosek, tipična greška ili
    tačnost, po danu ili prozoru), za poslednji dan i za istoriju (mali
    grafikon na pločici). Isti broj za svaki model, šta god da model radi.
    """
    if not dn or dn["normalno"] is None or not dn["dani"]:
        return None
    n, gore, dole = dn["normalno"], dn["gore"], dn["dole"]

    def procenat_granice(x: float) -> float:
        if gore is not None and x >= n:
            return (x - n) / ((gore - n) or 1e-12) * 100
        if dole is not None and x < n:
            return (n - x) / ((n - dole) or 1e-12) * 100
        return 0.0  # pomeraj u smeru koji nije problem (npr. greška se smanjila)

    istorija = [round(procenat_granice(d[2]), 1) for d in dn["dani"]][-30:]
    return {"procenat": istorija[-1], "istorija": istorija}


def pokazatelji(s: list[Rezultat], prikaz: list[Rezultat], g: Granice | None,
                p: Podesavanja, van: dict, sada: datetime, zona: ZoneInfo,
                istorijski: bool = False) -> list[dict]:
    """Nekoliko brojeva koji ukratko opisuju izvor: naziv, vrednost i objašnjenje."""
    lista = []
    j = s[-1].jedinica
    iskljuci = set(van)

    # 1. Poslednji rezultat i koliko je star.
    posl = s[-1]
    if posl.status == Status.GRESKA:
        vrednost = "greška modela"
    elif posl.kategorija is not None:
        vrednost = posl.kategorija
    elif posl.vrednost is not None:
        vrednost = sa_jedinicom(posl.vrednost, j)
    else:
        vrednost = "prazno"
    kada = f"{posl.vreme.astimezone(zona):%d.%m.%Y. %H:%M}" if istorijski else \
        f"{lokalno(posl.vreme, zona)}, {starost((sada - posl.vreme).total_seconds())}"
    lista.append({"naziv": "Poslednji rezultat", "vrednost": vrednost, "opis": kada})

    # 2. i 3. Koliko model greši sada, u odnosu na normalni period.
    prozor = g.prozor if g else 24
    if any(x.kategorija is not None for x in s):
        kt = kategorije_tacke(prikaz)
        if kt:
            skorasnje = kt[-prozor:]
            opis = f"poslednjih {len(skorasnje)} proverenih"
            if g and g.stopa_gresaka is not None:
                opis += f", normalno {procenat(1 - g.stopa_gresaka)}"
            lista.append({"naziv": "Tačnost", "opis": opis,
                          "vrednost": procenat(1 - mean(x for _, x in skorasnje))})
    else:
        e = greske(prikaz, iskljuci)
        if e and (g is None or g.drift_po_greski):
            skorasnje = e[-prozor:]
            opis = f"poslednjih {len(skorasnje)} rezultata"
            if g and g.drift_sredina is not None:
                opis += f", normalno {sa_jedinicom(g.drift_sredina, j)}"
            tipicna = median(abs(x) for _, x in skorasnje)
            lista.append({"naziv": "Tipična greška", "opis": opis,
                          "vrednost": sa_jedinicom(tipicna, j)})

            # Smer greške u celom prikazanom periodu, meren kao kod pristrasnosti.
            prosek = mean(x for _, x in e)
            prosek_apsolutnih = mean(abs(x) for _, x in e)
            u_istom_smeru = abs(prosek) / prosek_apsolutnih if prosek_apsolutnih else 0
            if u_istom_smeru > p.prag_pristrasnosti:
                smer = "model uglavnom daje više" if prosek > 0 else "model uglavnom daje manje"
            else:
                smer = "greši i naviše i naniže"
            lista.append({"naziv": "Prosečna greška", "opis": smer,
                          "vrednost": sa_jedinicom(prosek, j, znak=True, kao=prosek_apsolutnih)})
        else:
            vrednosti = [x.vrednost for x in prikaz
                         if x.vrednost is not None and x.vreme not in iskljuci]
            if vrednosti:
                skorasnje = vrednosti[-prozor:]
                opis = f"poslednjih {len(skorasnje)} rezultata"
                if g and g.drift_sredina is not None:
                    opis += f", normalno {sa_jedinicom(g.drift_sredina, j)}"
                lista.append({"naziv": "Prosečna vrednost", "opis": opis,
                              "vrednost": sa_jedinicom(mean(skorasnje), j)})

    # 4. Koliko rezultata je stiglo i koliko ih ne valja.
    prazni = sum(1 for x in prikaz if x.status == Status.OK and x.je_prazan)
    sa_greskom = sum(1 for x in prikaz if x.status == Status.GRESKA)
    nemogucih = sum(1 for x in prikaz if x.vreme in iskljuci)
    delovi = [f"{n} {tekst}" for n, tekst in
              [(prazni, "bez vrednosti"), (sa_greskom, "sa greškom"), (nemogucih, "neobičnih")] if n]
    lista.append({"naziv": "Rezultata u periodu", "vrednost": ceo_broj(len(prikaz)),
                  "opis": ", ".join(delovi) or "bez praznih i grešaka"})
    return lista


def naucene_granice(s: list[Rezultat], g: Granice, zona: ZoneInfo) -> list[str]:
    """
    Granice iz kalibracije rečima (opisi_granice iz koraka 3b), ali sa
    lokalnim vremenom i decimalnim zarezom, kao i sve ostalo na ekranu.
    """
    redovi = opisi_granice(s, g)[1:]  # prvi red je normalni period u UTC; pravimo ga ispod
    period = (f"normalni period: od {s[0].vreme.astimezone(zona):%d.%m.%Y. %H:%M} "
              f"do {g.kraj_osnove.astimezone(zona):%d.%m.%Y. %H:%M}")
    return [period] + redovi
