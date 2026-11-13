from datetime import datetime, timedelta
from statistics import mean

from app.provere.kvalitet import nemoguce_tacke, vrednosti
from app.provere.osnova import (
    Granice,
    Podesavanja,
    Tacke,
    klizni_prozori,
    ocekivani_korak,
    odskoci_od_suseda,
    trajanje,
)
from app.provere.tacnost import greske, kategorije_tacke, stat_prozora, tacke_za_drift
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
    j = f" {serija[0].jedinica}" if serija[0].jedinica else ""
    redovi = [
        f"normalni period: do {g.kraj_osnove:%d.%m.%Y %H:%M} (UTC)",
        f"rezultati obično stižu na svakih {trajanje(g.korak)}",
        f"izostanak: pauza duža od {trajanje(g.max_pauza)}",
    ]
    if g.max_odskok_vrednosti is not None:
        redovi.append(f"nemoguća vrednost: odskok od susednih veći od {g.max_odskok_vrednosti:.3g}{j}")
    if g.max_odskok_greske is not None:
        redovi.append(f"promašen skok: greška odskoči od susednih više od {g.max_odskok_greske:.3g}{j}")
    if g.drift_dozvoljeno is not None:
        sta = "tipična greška" if g.drift_po_greski else "prosečna vrednost"
        redovi.append(f"drift: {sta} se pomeri za više od {g.drift_dozvoljeno:.3g}{j} "
                      f"(normalno je oko {g.drift_sredina:.3g}{j})")
    if g.dozvoljen_rast_stope is not None:
        redovi.append(f"pad tačnosti: stopa grešaka poraste sa {g.stopa_gresaka:.0%} "
                      f"na više od {g.stopa_gresaka + g.dozvoljen_rast_stope:.0%}")
    return redovi