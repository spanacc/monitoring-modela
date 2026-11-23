"""
Provere: pronalaze probleme u rezultatima modela.

ŠTA JE OVO
----------
Glavna funkcija je `proveri_sve(rezultati)`. Prima rezultate (iz čitača,
korak 2) i vraća spisak nalaza, odnosno pronađenih problema.

Za svaku seriju (model + izvor) radi u dva koraka:

    1. kalibracija.py  NAUČI granice iz normalnog perioda
    2. provere         UPOREDE ostatak podataka sa tim granicama

Provere su podeljene u tri grupe, svaka u svom fajlu:

    dostupnost.py  da li rezultati stižu     (izostanak, duplikat, greška modela)
    kvalitet.py    da li su upotrebljivi     (prazne i nemoguće vrednosti)
    tacnost.py     da li je model dobar      (pristrasnost, drift, skok, pad tačnosti,
                                             promena odgovora kod kategorija)

Prve dve grupe rade za svaki model. Treća najviše koristi kad postoje
stvarne vrednosti, ali drift radi i bez njih.
"""

from datetime import datetime

from app.provere.dostupnost import (
    proveri_duplikate,
    proveri_greske_modela,
    proveri_izostanke,
)
from app.provere.kalibracija import kalibrisi
from app.provere.kvalitet import nemoguce_tacke, proveri_nemoguce, proveri_prazne
from app.provere.osnova import Nalaz, Ozbiljnost, Podesavanja, po_serijama
from app.provere.tacnost import (
    proveri_drift,
    proveri_pad_tacnosti,
    proveri_pristrasnost,
    proveri_promenu_kategorija,
    proveri_skokove,
)
from app.schema import Rezultat

__all__ = ["Nalaz", "Ozbiljnost", "Podesavanja", "proveri_sve"]


def proveri_sve(
    rezultati: list[Rezultat],
    p: Podesavanja | None = None,
    sada: datetime | None = None,
) -> list[Nalaz]:
    """
    Pokreće sve provere nad svim serijama i vraća nalaze poređane po vremenu.

    sada: trenutno vreme, za proveru da li je model "utihnuo". Ako se ne
          zada, uzima se vreme poslednjeg rezultata tog modela. Tako
          provera radi i na starim podacima, npr. iz simulatora.
    """
    p = p or Podesavanja()

    poslednji: dict[str, datetime] = {}
    for r in rezultati:
        poslednji[r.model] = max(poslednji.get(r.model, r.vreme), r.vreme)

    nalazi: list[Nalaz] = []
    for serija in po_serijama(rezultati).values():
        g = kalibrisi(serija, p)
        if g is None:
            continue  # samo jedan rezultat: nema sa čim da se poredi

        kraj = sada or poslednji[serija[0].model]
        iskljuci = set(nemoguce_tacke(serija, g))

        nalazi += proveri_izostanke(serija, g, kraj)
        nalazi += proveri_duplikate(serija, g)
        nalazi += proveri_greske_modela(serija, g)
        nalazi += proveri_prazne(serija, g)
        nalazi += proveri_nemoguce(serija, g)
        nalazi += proveri_pristrasnost(serija, g, p, iskljuci)
        nalazi += proveri_drift(serija, g, iskljuci)
        nalazi += proveri_skokove(serija, g, iskljuci)
        nalazi += proveri_pad_tacnosti(serija, g)
        nalazi += proveri_promenu_kategorija(serija, g)

    return sorted(nalazi, key=lambda n: (n.od, n.model, n.izvor))
