"""
Kalibracija: aplikacija sama računa granice za alarme.

ŠTA JE OVO
----------
Za svaku seriju (model + izvor) uzimamo NORMALNI PERIOD (početak podataka)
i gledamo kako se model tada ponašao:

    - najduža pauza između dva rezultata
    - koliko je najviše neka vrednost odskočila od svojih suseda
    - koliko je najviše greška odskočila od svojih suseda
    - koliko se najviše menjala tipična greška (ili vrednost) iz dana u dan
    - koliko se najviše menjala stopa pogrešnih kategorija

Granica za alarm je `rezerva` puta više od toga. Primer: ako je u normalnom
periodu najduža pauza bila 1 sat, a rezerva je 2, izostanak je pauza duža
od 2 sata. Za model kome su pauze normalno do 5 sati, granica je 10 sati.

ZAŠTO
-----
Tako nijedna granica nije izmišljena. Svaka je izvedena iz ponašanja baš
tog modela, na baš tom izvoru. Čovek bira samo rezervu, odnosno koliko je
aplikacija osetljiva.

PRETPOSTAVKA
------------
Normalni period je zaista bio normalan. Ako je model već tada imao
problem, aplikacija će ga naučiti kao normalno stanje.
"""

from datetime import datetime, timedelta
from statistics import mean

from app.provere.kvalitet import nemoguce_tacke, vrednosti
from app.provere.osnova import (
    Granice,
    Podesavanja,
    Tacke,
    klizni_prozori,
    lep_broj,
    ocekivani_korak,
    odskoci_od_suseda,
    trajanje,
)
from app.provere.tacnost import (
    greske,
    kategorije_odgovori,
    kategorije_tacke,
    najveci_pomak,
    stat_prozora,
    tacke_za_drift,
    udeli,
)
from app.schema import Rezultat

# Najmanje rezultata u normalnom periodu da bi se granica uopšte učila.
# Sa manje od toga "najgore što se desilo" nije pouzdano, pa se ta provera
# za tu seriju preskače dok se ne skupi dovoljno podataka.
NAJMANJE_TACAKA = 10


def kalibrisi(serija: list[Rezultat], p: Podesavanja) -> Granice | None:
    """
    Računa sve granice za jednu seriju. Vraća None ako serija ima samo
    jedan rezultat (tada nema ni šta da se poredi).
    """
    korak = ocekivani_korak(serija)
    if korak is None:
        return None

    if p.dana_osnove:
        # Normalni period: prvih `dana_osnove` dana. Ne pomera se kako podaci rastu.
        kraj = serija[0].vreme + timedelta(days=p.dana_osnove)
    else:
        # Normalni period: prvi `udeo_osnove` rezultata (bar 2).
        n = max(int(len(serija) * p.udeo_osnove), 2)
        kraj = serija[n - 1].vreme

    # Prozor: otprilike jedan dan rezultata, jer mnogi podaci imaju dnevni
    # ciklus, pa se tako ciklus poništi. Najmanje NAJMANJE_TACAKA rezultata.
    prozor = max(round(timedelta(days=1) / korak), NAJMANJE_TACAKA)

    # Kod čestih merenja (npr. svake sekunde) dan bi bio duži od celog
    # normalnog perioda: drift tada ne bi imao iz čega da uči, a odskok od
    # suseda bi se poredio sa celom serijom (i bio bi vrlo spor). Tada je
    # prozor 1/50 normalnog perioda, pa se normalno ponašanje uči iz
    # pedesetak prozora. Za podatke na sat, dan ili 15 minuta ništa se ne menja.
    u_osnovi = sum(1 for r in serija if r.vreme <= kraj)
    if u_osnovi < 2 * prozor:
        prozor = max(u_osnovi // 50, NAJMANJE_TACAKA)

    # --- izostanak: najduža pauza u normalnom periodu ---
    vremena = sorted({r.vreme for r in serija if r.vreme <= kraj})
    pauze = [b - a for a, b in zip(vremena, vremena[1:])]
    g = Granice(korak=korak, kraj_osnove=kraj, prozor=prozor,
                max_pauza=p.rezerva * max(pauze, default=korak))

    # --- nemoguća vrednost: najveći odskok vrednosti od suseda ---
    g.max_odskok_vrednosti = granica_odskoka(vrednosti(serija), kraj, prozor, p.rezerva)

    # Nemoguće vrednosti ne smeju da uđu u računanje grešaka.
    iskljuci = set(nemoguce_tacke(serija, g))

    # --- promašen skok: najveći odskok greške od suseda ---
    g.max_odskok_greske = granica_odskoka(greske(serija, iskljuci), kraj, prozor, p.rezerva)

    # --- drift: koliko se tipična greška (ili vrednost) menjala iz dana u dan ---
    tacke, g.drift_po_greski = tacke_za_drift(serija, iskljuci)
    osnova = [(t, x) for t, x in tacke if t <= kraj]
    if len(osnova) >= 2 * prozor:
        normalni = [stat_prozora(pr, g.drift_po_greski) for pr in klizni_prozori(osnova, prozor)]
        g.drift_sredina = mean(normalni)
        g.drift_dozvoljeno = p.rezerva * max(abs(s - g.drift_sredina) for s in normalni)

    # --- pad tačnosti: koliko se stopa grešaka kolebala iz dana u dan ---
    osnova_kat = [(t, x) for t, x in kategorije_tacke(serija) if t <= kraj]
    if len(osnova_kat) >= 2 * prozor:
        g.stopa_gresaka = mean(x for _, x in osnova_kat)
        # Kolebanje u oba smera (i gore i dole), jer je to pravo prirodno
        # kolebanje. Samo "gore" bi ponekad slučajno ispalo premalo.
        najvece_kolebanje = max(abs(mean(x for _, x in pr) - g.stopa_gresaka)
                                for pr in klizni_prozori(osnova_kat, prozor))
        # Bar jedna pogrešna kategorija više po prozoru, da granica ne bude 0
        # kad model u normalnom periodu nikad nije pogrešio.
        g.dozvoljen_rast_stope = p.rezerva * max(najvece_kolebanje, 1 / prozor)

    # --- promena odgovora: kad stvarnih kategorija nema, prati se odnos kategorija ---
    odgovori = [(t, k) for t, k in kategorije_odgovori(serija) if t <= kraj]
    if g.dozvoljen_rast_stope is None and len(odgovori) >= 2 * prozor:
        g.udeli_kategorija = udeli(odgovori)
        najvece = max(abs(najveci_pomak(udeli(pr), g.udeli_kategorija)[1])
                      for pr in klizni_prozori(odgovori, prozor))
        g.dozvoljen_pomak_udela = p.rezerva * max(najvece, 1 / prozor)

    return g


def granica_odskoka(tacke: Tacke, kraj: datetime, prozor: int, rezerva: float) -> float | None:
    """
    `rezerva` x najveći odskok od suseda u normalnom periodu.
    None ako u normalnom periodu ima premalo podataka, ili ništa nije odskakalo.
    """
    odskoci = odskoci_od_suseda(tacke, prozor)
    u_normalnom = [abs(o) for (t, _), o in zip(tacke, odskoci) if t <= kraj]
    if len(u_normalnom) < NAJMANJE_TACAKA or max(u_normalnom) == 0:
        return None
    return rezerva * max(u_normalnom)


def opisi_granice(serija: list[Rezultat], g: Granice) -> list[str]:
    """Naučene granice rečima, da čovek vidi šta je aplikacija zaključila."""
    j = serija[0].jedinica
    redovi = [
        f"normalni period: do {g.kraj_osnove:%d.%m.%Y %H:%M} (UTC)",
        f"rezultati obično stižu na svakih {trajanje(g.korak)}",
        f"izostanak: pauza duža od {trajanje(g.max_pauza)}",
    ]
    if g.max_odskok_vrednosti is not None:
        redovi.append(f"neobična vrednost: odskok od susednih veći od {lep_broj(g.max_odskok_vrednosti, j)}")
    if g.max_odskok_greske is not None:
        redovi.append(f"veliki promašaj: greška odskoči od susednih više od {lep_broj(g.max_odskok_greske, j)}")
    if g.drift_dozvoljeno is not None:
        sta = "tipična greška" if g.drift_po_greski else "prosečna vrednost"
        redovi.append(f"promena ponašanja: {sta} se pomeri za više od {lep_broj(g.drift_dozvoljeno, j)} "
                      f"(normalno je oko {lep_broj(g.drift_sredina, j)})")
    if g.dozvoljen_rast_stope is not None:
        redovi.append(f"pad tačnosti: stopa grešaka poraste sa {g.stopa_gresaka:.0%} "
                      f"na više od {g.stopa_gresaka + g.dozvoljen_rast_stope:.0%}")
    if g.dozvoljen_pomak_udela is not None:
        obicno = ", ".join(f"'{k}' {u:.0%}" for k, u in
                           sorted(g.udeli_kategorija.items(), key=lambda x: -x[1])[:3])
        redovi.append(f"promena odgovora: udeo neke kategorije se pomeri za više od "
                      f"{g.dozvoljen_pomak_udela:.0%} (obično: {obicno})")
    return redovi
