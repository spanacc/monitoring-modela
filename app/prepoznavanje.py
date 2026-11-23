"""
Automatsko prepoznavanje kolona.

ŠTA JE OVO
----------
Pravi podaci mogu imati bilo kakve nazive kolona: "Timestamp", "machine_id",
"Predicted Temp", "vreme_merenja"... Ovaj modul gleda nazive i sadržaj
kolona i pogađa koja kolona odgovara kom polju univerzalnog formata.

ZAŠTO
-----
Zato što o modelu ne znamo ništa. Ne želimo da za svaki novi model neko
ručno piše kod koji kaže "kolona X je vreme". Aplikacija to pogodi sama,
a čovek samo proveri i, ako treba, ispravi u JSON fajlu sa mapiranjem.

KAKO
----
U dva prolaza:
1. Po NAZIVU: tražimo poznate reči (time, datum, machine, predicted...).
   Sadržaj potvrđuje pogodak: kolona "time" mora zaista sadržati vremena.
2. Po SADRŽAJU: za polja koja nisu nađena po nazivu gledamo šta je u
   koloni (vremena, brojevi, tekst) i biramo najverovatniju.

Pogodak po sadržaju je manje siguran, pa se tako i označava.
"""

import json
import math
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, tzinfo
from pathlib import Path

from app.schema import Rezultat

# Nazivi polja univerzalnog formata: vreme, model, izvor, velicina...
POLJA = list(Rezultat.model_fields.keys())

# Tekstovi koji znače "nema podatka".
PRAZNO = {"", "nan", "null", "none", "na", "n/a", "-"}

# Reči po kojima prepoznajemo ulogu kolone, bez kvačica i malim slovima.
# Redosled je bitan: proverava se odozgo nadole i uzima se prva uloga
# koja odgovara. Zato "actual_value" postaje stvarna vrednost, a ne
# prognoza, iako sadrži reč "value".
RECI = {
    "vreme": {"vreme", "vrijeme", "time", "timestamp", "datetime", "date",
              "datum", "ts", "at", "dteday", "day"},
    # Sat u posebnoj koloni (uz datum u drugoj): "hr", "hour", "sat"...
    "doba_dana": {"hr", "hour", "sat", "cas", "hh", "hhmm"},
    "prognoza_jako": {"predicted", "prediction", "pred", "forecast", "prognoza",
                      "predvidjeno", "predvidjena", "predvidjeni", "predikcija",
                      "prognozirano", "procena", "procenjeno", "output", "yhat",
                      "score", "klasa", "class", "izlaz"},
    "stvarno": {"stvarno", "stvarna", "stvarni", "stvarnost", "izmereno", "izmerena",
                "actual", "observed", "measured", "true", "truth", "target", "label",
                "istina", "tacno", "ground"},
    "prognoza_slabo": {"value", "vrednost", "result", "rezultat"},
    "izvor": {"izvor", "source", "masina", "machine", "device", "uredjaj",
              "sensor", "senzor", "stanica", "station", "lokacija", "location",
              "site", "linija", "line", "asset", "node"},
    "status": {"status", "state"},
    "poruka": {"poruka", "message", "msg", "error", "greska", "err"},
    "jedinica": {"jedinica", "unit", "units", "uom"},
    "horizont_min": {"horizont", "horizon", "lead"},
    # Redni brojevi redova ne nose nikakvu informaciju, pa ih preskačemo.
    # Da ih ne preskočimo, "id" bi lako bio pogrešno uzet kao vrednost.
    "preskoci": {"id", "index", "idx", "row", "rb", "redni", "unnamed"},
}

# Formati vremena koji nisu ISO (ISO, npr. 2026-11-10T14:00, ide posebno).
FORMATI_VREMENA = [
    "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y",
    "%d.%m.%Y. %H:%M:%S", "%d.%m.%Y. %H:%M", "%d.%m.%Y.",
    "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d",
    "%Y-%m", "%m.%Y", "%m.%Y.",  # samo mesec: 2026-11, 11.2026
]
# Datumi sa kosim crtama su dvosmisleni: 11/10/2026 je 11. oktobar (dan pa
# mesec, kao u Evropi) ili 10. novembar (mesec pa dan, kao u Americi).
# Redosled se pogađa iz cele kolone (vidi `pogodi_redosled_datuma`).
KOSI_DM = ["%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"]
KOSI_MD = ["%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y"]


# ---------------------------------------------------------------------------
# Pomoćne funkcije: čitanje teksta iz fajla
# ---------------------------------------------------------------------------


def normalizuj(tekst: str) -> str:
    """'Mašina ID' -> 'masina_id'. Uklanja kvačice, velika slova i razmake."""
    tekst = tekst.strip().lower().replace("đ", "dj")
    tekst = unicodedata.normalize("NFKD", tekst)
    tekst = "".join(z for z in tekst if not unicodedata.combining(z))
    return re.sub(r"[^a-z0-9]+", "_", tekst).strip("_")


def je_prazno(tekst: str | None) -> bool:
    return tekst is None or tekst.strip().lower() in PRAZNO


def procitaj_broj(tekst: str) -> float | None:
    """'12,5' -> 12.5 i '1.234,5' -> 1234.5. Vraća None ako nije broj."""
    t = tekst.strip().replace(" ", "")
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):  # evropski zapis: 1.234,5
            t = t.replace(".", "").replace(",", ".")
        else:  # američki zapis: 1,234.5
            t = t.replace(",", "")
    else:
        t = t.replace(",", ".")
    try:
        broj = float(t)
    except ValueError:
        return None
    return broj if math.isfinite(broj) else None


def procitaj_vreme(tekst: str, zona: tzinfo, redosled: str = "dm") -> datetime | None:
    """
    Pretvara tekst u vreme. Vraća None ako tekst nije vreme.

    Ako vreme nema zonu (npr. '10.11.2026 14:00'), dodeljuje mu se `zona`,
    jer pretpostavljamo da je zapisano po lokalnom vremenu.
    redosled: za datume sa kosim crtama, "dm" (dan/mesec) ili "md" (mesec/dan).
    """
    t = tekst.strip()
    vreme = None

    # ISO zapis tražimo samo ako ima crticu, inače bi broj 20261110 bio
    # pogrešno pročitan kao datum.
    if "-" in t:
        try:
            vreme = datetime.fromisoformat(t)
        except ValueError:
            pass

    if vreme is None:
        formati = FORMATI_VREMENA + (KOSI_MD if redosled == "md" else KOSI_DM)
        for format_ in formati:
            try:
                vreme = datetime.strptime(t, format_)
                break
            except ValueError:
                pass

    if vreme is None:
        # Mašine često pišu vreme kao broj sekundi (ili milisekundi)
        # od 1.1.1970. To vreme je uvek u UTC.
        broj = procitaj_broj(t)
        if broj is not None and 1e9 <= broj < 1e10:
            return datetime.fromtimestamp(broj, timezone.utc)
        if broj is not None and 1e12 <= broj < 1e13:
            return datetime.fromtimestamp(broj / 1000, timezone.utc)
        return None

    if vreme.tzinfo is None:
        vreme = vreme.replace(tzinfo=zona)
    return vreme


# ---------------------------------------------------------------------------
# Profil kolone: šta se nalazi u njoj
# ---------------------------------------------------------------------------


@dataclass
class Profil:
    udeo_vremena: float  # koliki deo popunjenih vrednosti su vremena (0 do 1)
    udeo_brojeva: float  # koliki deo su brojevi
    razlicitih: int  # koliko različitih vrednosti ima
    popunjenih: int  # koliko vrednosti nije prazno
    redni: bool = False  # 1, 2, 3, 4...: redni broj reda, ne nosi informaciju
    samo_datum: bool = False  # vremena bez sata (npr. 2026-11-10), više puta isti dan
    udeo_doba_dana: float = 0.0  # koliki deo su sati (0-23) ili "14:30"


DOBA_DANA = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")


def je_doba_dana(tekst: str) -> bool:
    """'14:30', '14:30:00' ili ceo broj od 0 do 23 (sat u danu)."""
    t = tekst.strip()
    if DOBA_DANA.match(t):
        return True
    broj = procitaj_broj(t)
    return broj is not None and broj == int(broj) and 0 <= broj <= 23


def napravi_profil(vrednosti: list[str], redosled: str = "dm") -> Profil:
    popunjene = [v for v in vrednosti if not je_prazno(v)]
    if not popunjene:
        return Profil(0, 0, 0, 0)
    n = len(popunjene)
    vremena = [procitaj_vreme(v, timezone.utc, redosled) for v in popunjene]
    brojevi = [procitaj_broj(v) for v in popunjene]
    prava = [t for t in vremena if t is not None]
    celi = [b for b in brojevi if b is not None and b == int(b)]
    return Profil(
        udeo_vremena=len(prava) / n,
        udeo_brojeva=sum(b is not None for b in brojevi) / n,
        razlicitih=len(set(popunjene)),
        popunjenih=n,
        redni=(n >= 5 and len(celi) == n
               and all(b - a == 1 for a, b in zip(celi, celi[1:]))),
        samo_datum=(len(prava) >= 0.8 * n and len(prava) >= 2
                    and all(t.hour == t.minute == t.second == 0 for t in prava)
                    and len(set(prava)) < 0.5 * len(prava)),
        udeo_doba_dana=sum(je_doba_dana(v) for v in popunjene) / n,
    )


def je_tekst(p: Profil) -> bool:
    return p.popunjenih > 0 and p.udeo_brojeva < 0.9 and p.udeo_vremena < 0.8


def pogodi_redosled_datuma(vrednosti: list[str]) -> tuple[str, bool]:
    """
    Za datume sa kosim crtama: da li je prvo dan ili mesec. Gleda se da li
    je prvi broj ikad veći od 12 (onda je dan) ili drugi (onda je mesec).
    Vraća ("dm" ili "md", da li je sigurno).
    """
    prvi = drugi = 0
    for v in vrednosti:
        delovi = re.match(r"\s*(\d{1,2})/(\d{1,2})/\d{2,4}", v or "")
        if not delovi:
            continue
        prvi = max(prvi, int(delovi.group(1)))
        drugi = max(drugi, int(delovi.group(2)))
    if prvi > 12:
        return "dm", True
    if drugi > 12:
        return "md", True
    return "dm", prvi == 0 and drugi == 0  # bez kosih crta nema ni nedoumice


# ---------------------------------------------------------------------------
# Mapiranje: rezultat prepoznavanja
# ---------------------------------------------------------------------------


@dataclass
class Mapiranje:
    """Koja kolona iz fajla odgovara kom polju univerzalnog formata."""

    polja: dict[str, str] = field(default_factory=dict)  # polje -> kolona
    nacin: dict[str, str] = field(default_factory=dict)  # polje -> kako je nađeno
    neprepoznate: list[str] = field(default_factory=list)
    velicina: str = "vrednost"  # koristi se ako fajl nema kolonu 'velicina'
    redosled_datuma: str = "dm"  # za datume sa kosim crtama: dan/mesec ili mesec/dan
    napomene: list[str] = field(default_factory=list)  # na šta čovek treba da obrati pažnju

    def sacuvaj(self, putanja: Path) -> None:
        """Čuva mapiranje u JSON, da bi čovek mogao da ga pregleda i ispravi."""
        tekst = json.dumps(asdict(self), ensure_ascii=False, indent=2)
        Path(putanja).write_text(tekst, encoding="utf-8")

    @classmethod
    def ucitaj(cls, putanja: Path) -> "Mapiranje":
        return cls.iz_recnika(json.loads(Path(putanja).read_text(encoding="utf-8")))

    @classmethod
    def iz_recnika(cls, podaci: dict) -> "Mapiranje":
        """Mapiranje iz rečnika (JSON fajl ili podešavanja); nepoznata polja se preskaču."""
        poznata = {k: v for k, v in podaci.items() if k in cls.__dataclass_fields__}
        m = cls(**poznata)
        glavna = m.polja.get("vrednost") or m.polja.get("kategorija")
        if glavna and "velicina" not in podaci:
            m.velicina = normalizuj(glavna)
        return m


def uloga_po_nazivu(naziv: str) -> str | None:
    """Vraća ulogu kolone na osnovu reči u njenom nazivu, ili None ako ne zna."""
    reci = set(normalizuj(naziv).split("_"))
    for uloga, poznate in RECI.items():
        if reci & poznate:
            return uloga
    return None


def prepoznaj(kolone: list[str], redovi: list[dict]) -> Mapiranje:
    """Pogađa koja kolona je koje polje. Gleda samo prvih 500 redova."""
    uzorak = redovi[:500]
    m = Mapiranje()

    # Datumi sa kosim crtama: redosled dana i meseca se pogađa iz svih kolona
    # koje liče na datum, pre profila, jer profil zavisi od njega.
    sigurno = True
    for k in kolone:
        vrednosti_k = [r.get(k) or "" for r in uzorak]
        if any("/" in v for v in vrednosti_k[:50]):
            m.redosled_datuma, sig = pogodi_redosled_datuma(vrednosti_k)
            sigurno = sigurno and sig
    if not sigurno:
        m.napomene.append("Datumi sa kosim crtama (npr. 11/10/2026) su dvosmisleni. "
                          "Uzeto je da je prvo dan pa mesec; ako je obrnuto, promenite redosled.")

    profili = {k: napravi_profil([r.get(k) or "" for r in uzorak], m.redosled_datuma) for k in kolone}
    slobodne = list(kolone)

    def dodeli(polje: str, kolona: str, nacin: str) -> None:
        # Svako polje dobija samo jednu kolonu, i svaka kolona ide samo jednom polju.
        if polje not in m.polja and kolona in slobodne:
            m.polja[polje] = kolona
            m.nacin[polje] = nacin
            slobodne.remove(kolona)

    # --- 1. prolaz: po nazivu, uz proveru sadržaja ---
    for kolona in kolone:
        # Kolona koja se zove baš kao polje (npr. fajlovi iz simulatora)
        # uzima se bez daljeg pogađanja.
        if normalizuj(kolona) in POLJA:
            dodeli(normalizuj(kolona), kolona, "tačan naziv")
            continue

        uloga = uloga_po_nazivu(kolona)
        p = profili[kolona]

        # Redni broj reda (1, 2, 3...) ne nosi informaciju, ma kako se zvao
        # (rowid, instant, No...). Prepoznaje se po sadržaju.
        if p.redni and uloga not in ("vreme", "doba_dana"):
            slobodne.remove(kolona)
            continue
        # Naziv već kaže da je kolona prognoza ili stvarna vrednost; sadržaj
        # samo odlučuje da li je broj ili kategorija. Dovoljno je da je više
        # od pola vrednosti brojeva, da jedna pokvarena vrednost ne bi
        # pretvorila celu kolonu u kategoriju.
        broj_ili_prazno = p.popunjenih == 0 or p.udeo_brojeva >= 0.5

        if uloga == "vreme" and p.udeo_vremena >= 0.5:
            dodeli("vreme", kolona, "naziv kolone")
        elif uloga == "doba_dana" and p.udeo_doba_dana >= 0.9:
            dodeli("doba_dana", kolona, "naziv kolone")
        elif uloga in ("prognoza_jako", "prognoza_slabo"):
            # Isti naziv ("prediction") može da nosi broj ili kategoriju.
            # Sadržaj odlučuje koje je od ta dva.
            polje = "vrednost" if broj_ili_prazno else "kategorija"
            dodeli(polje, kolona, "naziv kolone")
        elif uloga == "stvarno":
            polje = "stvarna_vrednost" if broj_ili_prazno else "stvarna_kategorija"
            dodeli(polje, kolona, "naziv kolone")
        elif uloga in ("izvor", "status", "poruka", "jedinica", "horizont_min"):
            dodeli(uloga, kolona, "naziv kolone")
        elif uloga == "preskoci":
            slobodne.remove(kolona)

    # --- 2. prolaz: po sadržaju, za ono što nije nađeno po nazivu ---
    def prva(uslov) -> str | None:
        return next((k for k in slobodne if uslov(profili[k])), None)

    nesigurno = "sadržaj (proveriti)"

    if "vreme" not in m.polja:
        k = prva(lambda p: p.popunjenih > 0 and p.udeo_vremena >= 0.8)
        if k:
            dodeli("vreme", k, nesigurno)

    # Datum u jednoj koloni, a sat u drugoj (npr. "dteday" i "hr"): bez sata
    # bi sva merenja jednog dana bila u istom trenutku. Sat se traži po
    # sadržaju: brojevi 0-23 sa bar 8 različitih, ili "14:30".
    vreme_k = m.polja.get("vreme")
    if vreme_k and profili[vreme_k].samo_datum and "doba_dana" not in m.polja:
        k = prva(lambda p: p.udeo_doba_dana >= 0.95 and p.razlicitih >= 8 and not p.redni)
        if k:
            dodeli("doba_dana", k, nesigurno)
        else:
            m.napomene.append(f"U koloni '{vreme_k}' je samo datum, bez sata, a isti datum se "
                              "ponavlja. Ako je sat u drugoj koloni, označite je kao doba dana.")
    if "doba_dana" in m.polja and "vreme" not in m.polja:
        slobodne.append(m.polja.pop("doba_dana"))  # sat bez datuma ne znači ništa
        m.nacin.pop("doba_dana", None)

    if "vrednost" not in m.polja and "kategorija" not in m.polja:
        # Od brojčanih kolona bira se ona sa najviše različitih vrednosti
        # (merenje, ne šifra kao "godišnje doba" 1-4); kod istog broja
        # poslednja, jer rezultat modela obično stoji na kraju tabele.
        brojcane = [k for k in slobodne if profili[k].popunjenih > 0 and profili[k].udeo_brojeva >= 0.9]
        if brojcane:
            k = max(reversed(brojcane), key=lambda k: profili[k].razlicitih)
            dodeli("vrednost", k, nesigurno)

    if "izvor" not in m.polja:
        k = prva(lambda p: je_tekst(p) and p.razlicitih <= 200)
        if k:
            dodeli("izvor", k, nesigurno)

    if "vrednost" not in m.polja and "kategorija" not in m.polja:
        k = prva(lambda p: je_tekst(p) and p.razlicitih <= 200)
        if k:
            dodeli("kategorija", k, nesigurno)

    # Šta model predviđa: naziv kolone sa rezultatom, npr. "predicted_temp".
    glavna = m.polja.get("vrednost") or m.polja.get("kategorija")
    if glavna:
        m.velicina = normalizuj(glavna)

    m.neprepoznate = [k for k in kolone if k not in m.polja.values()]
    return m
