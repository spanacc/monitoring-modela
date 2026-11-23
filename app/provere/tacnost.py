"""
Provere tačnosti i ponašanja modela.

- pristrasnost:  model stalno greši u istom smeru (npr. uvek predviđa više)
- drift:         model vremenom postaje lošiji, ili mu se ponašanje menja
- promasen_skok: model je naglo i jako promašio (npr. nije video nagli skok)
- pad_tacnosti:  isto što i drift, ali za modele koji vraćaju kategorije

Sve granice dolaze iz kalibracije (naučene iz normalnog perioda). Ovde se
samo poredi "sada" sa tim granicama.

Za pristrasnost, promašen skok i pad tačnosti potrebne su stvarne
vrednosti. Drift radi i bez njih: tada prati samo da li su se vrednosti
koje model vraća pomerile. Tako aplikacija nešto korisno javlja i ako
stvarne vrednosti nikad ne dobijemo.
"""

from datetime import datetime
from statistics import mean, median

from app.provere.osnova import (
    Granice,
    Nalaz,
    Ozbiljnost,
    Podesavanja,
    Tacke,
    lep_broj,
    napravi,
    odskoci_od_suseda,
    prozori,
    u_intervale,
)
from app.schema import Rezultat


# ---------------------------------------------------------------------------
# Priprema podataka (koristi je i kalibracija, da bi računala isto)
# ---------------------------------------------------------------------------


def greske(serija: list[Rezultat], iskljuci: set[datetime]) -> Tacke:
    """
    Greška = vrednost koju je model dao - stvarna vrednost.
    Pozitivna greška znači da je model predvideo više nego što je bilo.
    Nemoguće vrednosti (`iskljuci`) se preskaču, jer bi jedna vrednost
    9999 sama pokvarila sve proseke.
    """
    return [
        (r.vreme, r.vrednost - r.stvarna_vrednost)
        for r in serija
        if r.vrednost is not None and r.stvarna_vrednost is not None
        and r.vreme not in iskljuci
    ]


def tacke_za_drift(serija: list[Rezultat], iskljuci: set[datetime]) -> tuple[Tacke, bool]:
    """
    Šta drift prati: grešku, ako ima dovoljno stvarnih vrednosti (bar za
    polovinu rezultata), a inače same vrednosti koje model vraća.
    Vraća tačke i True ako se prati greška.
    """
    sa_greskom = greske(serija, iskljuci)
    vrednosti = [(r.vreme, r.vrednost) for r in serija
                 if r.vrednost is not None and r.vreme not in iskljuci]
    if len(sa_greskom) >= len(vrednosti) / 2:
        return [(t, abs(e)) for t, e in sa_greskom], True
    return vrednosti, False


def stat_prozora(prozor: Tacke, po_greski: bool) -> float:
    """
    Jedan broj koji opisuje prozor.
    - Za grešku: medijana, da je jedan nagli promašaj ne pomeri
      (njega prijavljuje provera skokova).
    - Za vrednosti: prosek. Nemoguće vrednosti su već isključene, a prosek
      je mirniji kad podaci imaju dnevni ciklus, pa daje manje lažnih uzbuna.
    """
    return median(x for _, x in prozor) if po_greski else mean(x for _, x in prozor)


def kategorije_tacke(serija: list[Rezultat]) -> Tacke:
    """Za modele sa kategorijama: 1 ako je model pogrešio, 0 ako je pogodio."""
    return [(r.vreme, 0.0 if r.kategorija == r.stvarna_kategorija else 1.0)
            for r in serija
            if r.kategorija is not None and r.stvarna_kategorija is not None]


def kategorije_odgovori(serija: list[Rezultat]) -> list[tuple[datetime, str]]:
    """Sve kategorije koje je model vratio, sa vremenom (i bez stvarnih vrednosti)."""
    return [(r.vreme, r.kategorija) for r in serija if r.kategorija is not None]


def udeli(prozor: list[tuple[datetime, str]]) -> dict[str, float]:
    """Koliki deo odgovora u prozoru je koja kategorija: {'kvar': 0.1, 'ispravno': 0.9}."""
    n = len(prozor)
    brojevi: dict[str, int] = {}
    for _, k in prozor:
        brojevi[k] = brojevi.get(k, 0) + 1
    return {k: b / n for k, b in brojevi.items()}


def najveci_pomak(udeo: dict[str, float], normalno: dict[str, float]) -> tuple[str, float]:
    """Kategorija čiji se udeo najviše pomerio od normalnog, i za koliko."""
    # Kod jednakog pomeraja bira se kategorija koja je PORASLA (npr. "kvar" sa
    # 10% na 90%), jer to čoveku više govori; i uvek ista, bez slučajnosti.
    kat = max(sorted(set(udeo) | set(normalno)),
              key=lambda k: (round(abs(udeo.get(k, 0) - normalno.get(k, 0)), 9), udeo.get(k, 0) > normalno.get(k, 0)))
    return kat, udeo.get(kat, 0) - normalno.get(kat, 0)


def periodi(svi_prozori: list[Tacke], oznake: list[bool]) -> list[tuple[datetime, datetime]]:
    """
    Spaja uzastopne označene prozore u periode. Zadržava samo periode od
    bar 2 prozora zaredom: jedan loš prozor može biti slučajnost, dva
    zaredom retko jesu. Tako se smanjuju lažne uzbune.
    """
    rezultat, niz = [], []
    for prozor, oznacen in zip(svi_prozori + [[]], oznake + [False]):
        if oznacen:
            niz.append(prozor)
            continue
        if len(niz) >= 2:
            rezultat.append((niz[0][0][0], niz[-1][-1][0]))
        niz = []
    return rezultat


# ---------------------------------------------------------------------------
# Provere
# ---------------------------------------------------------------------------


def proveri_pristrasnost(serija: list[Rezultat], g: Granice, p: Podesavanja,
                         iskljuci: set[datetime]) -> list[Nalaz]:
    """
    Pristrasnost = model stalno greši u istom smeru.

    Merimo koliki deo greške je "uvek u istom smeru": |prosek grešaka|
    podeljeno sa prosekom |grešaka|. Ako model greši nasumično (malo gore,
    malo dole), to je blizu 0. Ako uvek predviđa više, to je blizu 1.

    Mora da važi i u normalnom periodu i za ceo period. Ako se pristrasnost
    pojavi tek kasnije, to je promena ponašanja i prijavljuje je drift.
    """
    tacke = greske(serija, iskljuci)
    osnova = [(t, e) for t, e in tacke if t <= g.kraj_osnove]
    if len(osnova) < 10:
        return []

    def u_istom_smeru(deo: Tacke) -> float:
        prosek_apsolutnih = mean(abs(e) for _, e in deo)
        return abs(mean(e for _, e in deo)) / prosek_apsolutnih if prosek_apsolutnih else 0.0

    if u_istom_smeru(osnova) <= p.prag_pristrasnosti or u_istom_smeru(tacke) <= p.prag_pristrasnosti:
        return []

    pomak = mean(e for _, e in tacke)
    smer = "veće" if pomak > 0 else "manje"
    return [napravi(
        "pristrasnost", serija, tacke[0][0], tacke[-1][0], Ozbiljnost.UPOZORENJE,
        f"Model stalno daje {smer} vrednosti od stvarnih, "
        f"u proseku za {lep_broj(abs(pomak), serija[0].jedinica)}.",
    )]


def proveri_drift(serija: list[Rezultat], g: Granice,
                  iskljuci: set[datetime]) -> list[Nalaz]:
    """
    Drift = ponašanje modela se vremenom menja.

    Podaci posle normalnog perioda se dele na prozore (otprilike po jedan
    dan). Prozor je sumnjiv ako se njegov broj (tipična greška, ili
    prosečna vrednost) pomeri od normalnog više od `g.drift_dozvoljeno`.
    """
    if g.drift_dozvoljeno is None:
        return []
    tacke, _ = tacke_za_drift(serija, iskljuci)
    kasniji = prozori([(t, x) for t, x in tacke if t > g.kraj_osnove], g.prozor)

    if g.drift_po_greski:
        # Gledamo samo rast greške: ako model postane bolji, to nije problem.
        oznake = [stat_prozora(pr, True) - g.drift_sredina > g.drift_dozvoljeno
                  for pr in kasniji]
        opis = "Greška modela je postala znatno veća nego u normalnom periodu."
    else:
        oznake = [abs(stat_prozora(pr, False) - g.drift_sredina) > g.drift_dozvoljeno
                  for pr in kasniji]
        opis = ("Vrednosti koje model vraća primetno su se pomerile u odnosu na "
                "normalni period. Stvarne vrednosti nisu poznate, pa se ne zna da li "
                "je model pogrešio ili se stvarnost promenila.")

    return [napravi("drift", serija, od, do, Ozbiljnost.UPOZORENJE, opis)
            for od, do in periodi(kasniji, oznake)]


def proveri_skokove(serija: list[Rezultat], g: Granice,
                    iskljuci: set[datetime]) -> list[Nalaz]:
    """
    Promašen skok = greška naglo odskoči od grešaka oko nje više od
    `g.max_odskok_greske` (naučeno iz normalnog perioda).

    Spor drift ili stalna pristrasnost NE okidaju ovu proveru, jer se i
    susedne greške pomeraju zajedno sa njima. Nagao promašaj je okida.
    """
    if g.max_odskok_greske is None:
        return []
    tacke = greske(serija, iskljuci)
    odskoci = odskoci_od_suseda(tacke, g.prozor)
    vremena = [t for (t, _), o in zip(tacke, odskoci) if abs(o) > g.max_odskok_greske]

    return [napravi("promasen_skok", serija, od, do, Ozbiljnost.KRITICNO,
                    "Model je naglo i jako promašio stvarnu vrednost "
                    "(npr. nije predvideo nagli skok ili pad).")
            for od, do in u_intervale(vremena, g.korak)]


def proveri_pad_tacnosti(serija: list[Rezultat], g: Granice) -> list[Nalaz]:
    """
    Za modele koji vraćaju kategorije (npr. ispravno / neispravno).

    Prozor je sumnjiv ako mu stopa grešaka poraste iznad normalne više
    od `g.dozvoljen_rast_stope` (naučeno iz normalnog perioda).
    """
    if g.dozvoljen_rast_stope is None:
        return []
    kasnije = [(t, x) for t, x in kategorije_tacke(serija) if t > g.kraj_osnove]
    kasniji = prozori(kasnije, g.prozor)
    oznake = [mean(x for _, x in pr) - g.stopa_gresaka > g.dozvoljen_rast_stope
              for pr in kasniji]

    nalazi = []
    for od, do in periodi(kasniji, oznake):
        u_periodu = [x for t, x in kasnije if od <= t <= do]
        nalazi.append(napravi(
            "pad_tacnosti", serija, od, do, Ozbiljnost.UPOZORENJE,
            f"Tačnost je pala sa {1 - g.stopa_gresaka:.0%} na {1 - mean(u_periodu):.0%}.",
        ))
    return nalazi


def proveri_promenu_kategorija(serija: list[Rezultat], g: Granice) -> list[Nalaz]:
    """
    Za modele koji vraćaju kategorije, a stvarni odgovor nije poznat.

    Prati koliki deo odgovora je koja kategorija. Ako se taj odnos u dva
    prozora zaredom pomeri više nego što se ikad pomerao u normalnom
    periodu (puta rezerva), model se ponaša drugačije: npr. odjednom za
    80% slučajeva kaže "kvar", a ranije za 10%. Ne zna se da li je model
    pogrešio ili se stvarnost promenila, ali čovek treba da pogleda.
    """
    if g.dozvoljen_pomak_udela is None:
        return []
    kasnije = [(t, k) for t, k in kategorije_odgovori(serija) if t > g.kraj_osnove]
    kasniji = prozori(kasnije, g.prozor)
    oznake = [abs(najveci_pomak(udeli(pr), g.udeli_kategorija)[1]) > g.dozvoljen_pomak_udela
              for pr in kasniji]

    nalazi = []
    for od, do in periodi(kasniji, oznake):
        u_periodu = udeli([(t, k) for t, k in kasnije if od <= t <= do])
        kat, pomak = najveci_pomak(u_periodu, g.udeli_kategorija)
        nalazi.append(napravi(
            "promena_kategorija", serija, od, do, Ozbiljnost.UPOZORENJE,
            f"Model daje odgovor '{kat}' u {u_periodu.get(kat, 0):.0%} slučajeva, a u normalnom "
            f"periodu u {g.udeli_kategorija.get(kat, 0):.0%}. Stvarni odgovori nisu poznati, pa se "
            "ne zna da li je model pogrešio ili se stvarnost promenila.",
        ))
    return nalazi
