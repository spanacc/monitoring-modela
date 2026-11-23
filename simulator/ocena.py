"""
Ocena provera: da li pronalaze sve probleme koje je simulator ubacio.

ŠTA JE OVO
----------
Simulator je zapisao spisak problema koje je namerno ubacio (korak 1).
Ovde puštamo provere nad simuliranim podacima i poredimo šta su našle
sa tim spiskom:

- pronađeni: ubačeni problemi koje su provere našle
- promašeni: ubačeni problemi koje NISU našle (provera je preslaba)
- lažni:     nalazi kojima ne odgovara nijedan ubačen problem
             (provera je preosetljiva, tj. lažna uzbuna)

Cilj je: svi pronađeni, nijedan lažni.

KAKO SE KORISTI
---------------
    python -m simulator.pokreni      # prvo napraviti podatke
    python -m simulator.ocena
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.citac import ucitaj_csv
from app.provere import Nalaz, proveri_sve


@dataclass
class Ocena:
    pronadjeni: list[dict]
    promaseni: list[dict]
    lazni: list[Nalaz]


# Pad tačnosti se bez stvarnih vrednosti vidi kao promena odgovora modela.
SRODNI = {"pad_tacnosti": {"pad_tacnosti", "promena_kategorija"}}


def poklapa(nalaz: Nalaz, problem: dict) -> bool:
    """Isti (ili srodan) tip, isti model i izvor, i vremena se bar delom preklapaju."""
    od = datetime.fromisoformat(problem["od"])
    do = datetime.fromisoformat(problem["do"])
    return (
        nalaz.tip in SRODNI.get(problem["tip"], {problem["tip"]})
        and nalaz.model == problem["model"]
        and nalaz.izvor == problem["izvor"]
        and nalaz.od < do
        and od < nalaz.do
    )


def oceni(nalazi: list[Nalaz], problemi: list[dict]) -> Ocena:
    pronadjeni = [pr for pr in problemi if any(poklapa(n, pr) for n in nalazi)]
    promaseni = [pr for pr in problemi if pr not in pronadjeni]
    lazni = [n for n in nalazi if not any(poklapa(n, pr) for pr in problemi)]
    return Ocena(pronadjeni, promaseni, lazni)


def main() -> None:
    folder = Path("data/simulirano")
    putanja_problema = folder / "ubaceni_problemi.json"
    if not putanja_problema.exists():
        raise SystemExit("Nema simuliranih podataka. Prvo pokrenite: python -m simulator.pokreni")

    rezultati = []
    for csv_fajl in sorted(folder.glob("*.csv")):
        rezultati += ucitaj_csv(csv_fajl).rezultati
    problemi = json.loads(putanja_problema.read_text(encoding="utf-8"))

    nalazi = proveri_sve(rezultati)
    ocena = oceni(nalazi, problemi)

    print(f"Pronađeno {len(ocena.pronadjeni)} od {len(problemi)} ubačenih problema.")
    print(f"Lažnih uzbuna: {len(ocena.lazni)}\n")
    for pr in problemi:
        oznaka = "OK      " if pr in ocena.pronadjeni else "PROMAŠEN"
        print(f"  [{oznaka}] {pr['model']:10} {pr['izvor']:9} {pr['tip']}")
    for n in ocena.lazni:
        print(f"  [LAŽNA  ] {n.model:10} {n.izvor:9} {n.tip}: {n.opis}")


if __name__ == "__main__":
    main()
