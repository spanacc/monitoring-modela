"""
Pokreće simulator i čuva rezultate u CSV fajlove.

KAKO SE KORISTI
---------------
    python -m simulator.pokreni                  # 30 dana, u data/simulirano/
    python -m simulator.pokreni --dani 60        # 60 dana
    python -m simulator.pokreni --seed 7         # drugi (ali isto realni) podaci

ŠTA NAPRAVI
-----------
    data/simulirano/senzori.csv
    data/simulirano/potrosnja.csv
    data/simulirano/kvalitet.csv
    data/simulirano/ubaceni_problemi.json   # spisak namerno ubačenih problema

ZAŠTO CSV
---------
CSV je najjednostavniji format: otvara se u Excelu, svaki program ume da ga
pročita, i verovatno je pravi model negde upravo tako i izbacuje rezultate.
Tako ćemo u sledećem koraku, kad pravimo učitavanje, probati baš realan slučaj.
"""

import argparse
import csv
import json
from pathlib import Path

from app.schema import Rezultat
from simulator.modeli import SVI_MODELI

KOLONE = list(Rezultat.model_fields.keys())


def sacuvaj_csv(rezultati: list[Rezultat], putanja: Path) -> None:
    with putanja.open("w", newline="", encoding="utf-8") as f:
        pisac = csv.DictWriter(f, fieldnames=KOLONE)
        pisac.writeheader()
        for r in rezultati:
            # mode="json" pretvara vreme u tekst, a prazne vrednosti u None
            red = r.model_dump(mode="json")
            pisac.writerow({k: ("" if v is None else v) for k, v in red.items()})


def main() -> None:
    parser = argparse.ArgumentParser(description="Pravi izmišljene rezultate modela.")
    parser.add_argument("--dani", type=int, default=30, help="koliko dana podataka")
    parser.add_argument("--seed", type=int, default=0, help="seme za slučajne brojeve")
    parser.add_argument("--izlaz", type=Path, default=Path("data/simulirano"))
    args = parser.parse_args()

    args.izlaz.mkdir(parents=True, exist_ok=True)
    svi_problemi = []

    for i, (naziv, simuliraj) in enumerate(SVI_MODELI.items()):
        sim = simuliraj(dani=args.dani, seed=args.seed * 10 + i + 1)
        sacuvaj_csv(sim.rezultati, args.izlaz / f"{naziv}.csv")
        svi_problemi.extend(sim.problemi_kao_recnik())
        print(f"{naziv:10} {len(sim.rezultati):6} rezultata, "
              f"{len(sim.problemi)} ubačenih problema")

    with (args.izlaz / "ubaceni_problemi.json").open("w", encoding="utf-8") as f:
        json.dump(svi_problemi, f, ensure_ascii=False, indent=2)

    print(f"\nSačuvano u: {args.izlaz.resolve()}")


if __name__ == "__main__":
    main()