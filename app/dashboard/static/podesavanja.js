/*
 * Stranica sa podešavanjima: šta se prati, dodavanje i uklanjanje fajlova
 * i "Proveri sada". Ovde se dolazi retko (zupčanik na glavnoj stranici).
 */

import {
  $, api, broj, h, mnozina, obavesti, postaviZonu, vremeGodina,
} from "./alati.js";

const st = { izvori: [], predlog: null };

async function osvezi() {
  try {
    const [stanje, izvori, pregled] = await Promise.all([api("/api/stanje"), api("/api/izvori"), api("/api/pregled?dana=7")]);
    postaviZonu(pregled.zona);
    st.izvori = izvori;
    const n = stanje.nadzor?.sekundi;
    $("provera-opis").textContent = n
      ? `Radi sama, na svakih ${n < 120 ? `${n} s` : `${Math.round(n / 60)} min`}. Ovde se može pokrenuti odmah, bez čekanja.`
      : "Automatska provera nije uključena. Pokrenite je ovde.";
    $("demo").hidden = !stanje.demo;
    crtajPracene();
  } catch (e) {
    obavesti(e.message, true);
  }
}

function crtajPracene() {
  if (!$("praceno-lista")) return;
  if (!st.izvori.length) {
    $("praceno-lista").replaceChildren(h("li", { class: "prazno" },
      "Još se ništa ne prati. Kliknite Dodaj podatke i ubacite fajl koji model pravi, ili upišite folder u kome ih ostavlja."));
    return;
  }
  $("praceno-lista").replaceChildren(...st.izvori.map((i) => h("li", { class: "praceno__stavka" },
    h("div", null,
      h("strong", null, i.model),
      h("span", { class: "praceno__putanja" }, i.putanja),
      i.kolone ? h("span", { class: "praceno__napomena" }, `${i.kolone.length} ${mnozina(i.kolone.length, ["kolona", "kolone", "kolona"])} kao izvori`) : null,
      i.istorijski ? h("span", { class: "praceno__napomena" }, "stari podaci") : null),
    h("button", {
      type: "button", class: "dugme dugme--tiho dugme--malo",
      onclick: async (e) => {
        if (!confirm(`Ukloniti "${i.model}" sa spiska i obrisati njegove rezultate i probleme iz baze? Sam fajl se ne dira.`)) return;
        e.currentTarget.disabled = true;
        try {
          await api(`/api/izvori/${encodeURIComponent(i.model)}`, null, "DELETE");
          obavesti(`"${i.model}" više se ne prati.`);
          await osvezi();
        } catch (greska) {
          e.currentTarget.disabled = false;
          obavesti(greska.message, true);
        }
      },
    }, "Ukloni"))));
}

// ---------------------------------------------------------------------------
// Dodavanje podataka: fajl ili putanja -> predlog kolona -> potvrda
// ---------------------------------------------------------------------------

function otvoriDodavanje() {
  st.predlog = null;
  korakFajl();
  $("dijalog").showModal();
}

function korakFajl(greska = null) {
  $("dijalog-naslov").textContent = "Dodaj podatke";
  const ulaz = h("input", { type: "file", accept: ".csv,.txt,text/csv,text/plain", id: "fajl-ulaz" });
  ulaz.addEventListener("change", () => { if (ulaz.files[0]) posaljiFajl(ulaz.files[0]); });
  const zona = h("label", { class: "ubaci", for: "fajl-ulaz" },
    h("span", { class: "ubaci__ikona", "aria-hidden": "true" }, "⤓"),
    h("span", { class: "ubaci__tekst" }, "Izaberite CSV fajl ili ga prevucite ovde"),
    h("span", { class: "ubaci__malo" }, "fajl koji model pravi; Excel tabela sačuvana kao CSV takođe radi"),
    ulaz);
  for (const ime of ["dragenter", "dragover"]) {
    zona.addEventListener(ime, (e) => { e.preventDefault(); zona.classList.add("ubaci--preko"); });
  }
  zona.addEventListener("dragleave", () => zona.classList.remove("ubaci--preko"));
  zona.addEventListener("drop", (e) => {
    e.preventDefault();
    zona.classList.remove("ubaci--preko");
    const f = e.dataTransfer.files[0];
    if (f) posaljiFajl(f);
  });

  const putanja = h("input", { type: "text", id: "putanja-ulaz", maxlength: 1000, spellcheck: "false",
    placeholder: "/Users/ime/rezultati/model.csv  ili  /Users/ime/rezultati" });
  const pogledaj = h("button", { type: "button", class: "dugme dugme--tiho" }, "Pogledaj");
  pogledaj.addEventListener("click", () => { if (putanja.value.trim()) posaljiPutanju(putanja.value.trim(), pogledaj); });
  putanja.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); pogledaj.click(); } });

  $("dijalog-telo").replaceChildren(...[
    h("p", { class: "dijalog__uvod" }, "Aplikacija sama prepozna koja kolona je vreme, a koja rezultat modela. Vi samo potvrdite."),
    greska ? h("p", { class: "dijalog__greska", role: "alert" }, greska) : null,
    zona,
    h("p", { class: "ili" }, "ili"),
    h("label", { class: "polje" }, h("span", null, "Fajl ili folder koji već postoji na ovom računaru"),
      h("div", { class: "polje__red" }, putanja, pogledaj)),
    h("p", { class: "dijalog__napomena" },
      "Folder: prate se svi CSV fajlovi u njemu, i oni koji se tek pojave. Ovo je za pravi rad, kad model sam ostavlja fajlove. "
      + "Aplikacija ih samo čita i ništa u njima ne menja."),
  ].filter(Boolean));
}

function prikaziCekanje(tekst) {
  $("dijalog-telo").replaceChildren(h("p", { class: "dijalog__cekanje" }, tekst));
}

async function posaljiFajl(fajl) {
  prikaziCekanje(`Čitam ${fajl.name}…`);
  try {
    const odgovor = await fetch("/api/izvori/predlog", {
      method: "POST", body: fajl,
      headers: { "X-Dashboard": "1", "X-Fajl": encodeURIComponent(fajl.name), "Content-Type": "application/octet-stream" },
    });
    if (!odgovor.ok) throw new Error((await odgovor.json()).detail ?? `Greška ${odgovor.status}.`);
    st.predlog = await odgovor.json();
    korakPotvrda();
  } catch (e) {
    korakFajl(e.message === "Failed to fetch" ? "Server ne odgovara." : e.message);
  }
}

async function posaljiPutanju(putanja, dugme) {
  dugme.disabled = true;
  try {
    st.predlog = await api("/api/izvori/predlog", { putanja });
    korakPotvrda();
  } catch (e) {
    korakFajl(e.message);
  }
}

/** Drugi korak: šta je prepoznato, sa mogućnošću ispravke, pa "Dodaj i proveri". */
function korakPotvrda(greska = null) {
  const pr = st.predlog;
  $("dijalog-naslov").textContent = "Proverite šta je prepoznato";
  const kolone = pr.kolone;
  const opisKolone = (k) => `${k.naziv}  (${k.vrsta}${k.razlicitih > 1 ? `, ${broj(k.razlicitih, 0)} različitih` : ""})`;

  const model = h("input", { type: "text", value: pr.model, maxlength: 100, required: true, spellcheck: "false" });
  const istorijski = h("input", { type: "checkbox", checked: pr.istorijski });
  const siroka = h("input", { type: "radio", name: "oblik", value: "siroka", checked: pr.siroka });
  const uska = h("input", { type: "radio", name: "oblik", value: "uska", checked: !pr.siroka });
  const dm = h("input", { type: "radio", name: "redosled", value: "dm", checked: pr.redosled_datuma === "dm" });
  const md = h("input", { type: "radio", name: "redosled", value: "md", checked: pr.redosled_datuma === "md" });

  const izbori = {};
  const poljaUska = ["vrednost", "kategorija", "stvarna_vrednost", "stvarna_kategorija", "izvor"];
  const poljaSvuda = pr.polja_za_izbor.filter((p) => !poljaUska.includes(p.polje));
  const napraviIzbor = (polje) => {
    const sel = h("select", null, h("option", { value: "" }, "—"),
      ...kolone.map((k) => h("option", { value: k.naziv, selected: pr.polja[polje] === k.naziv }, opisKolone(k))));
    izbori[polje] = sel;
    return sel;
  };
  const redPolja = (p) => h("label", { class: "polje polje--izbor", title: p.opis },
    h("span", null, p.naziv, p.polje === "vreme" ? " *" : ""), napraviIzbor(p.polje));

  const kvadratici = {};
  const listaKolona = h("div", { class: "kolone-izbor" }, ...pr.brojcane.map((naziv) => {
    const k = kolone.find((x) => x.naziv === naziv);
    // Unapred označene: merenja (mnogo različitih vrednosti), ne šifre (mesec 1-12, dan u nedelji 0-6).
    const cb = h("input", { type: "checkbox", value: naziv, checked: pr.brojcane.length <= 3 || k.razlicitih >= 25 });
    kvadratici[naziv] = cb;
    return h("label", { class: "kolone-izbor__stavka" }, cb, h("span", null, naziv),
      h("span", { class: "kolone-izbor__malo" }, `${broj(k.razlicitih, 0)} različitih`));
  }));
  const deoSiroka = h("div", { class: "deo-oblika" },
    h("p", { class: "dijalog__napomena" }, "Svaka označena kolona postaje poseban izvor (npr. senzor), a pratiće se zajedno."),
    listaKolona);
  const deoUska = h("div", { class: "deo-oblika polja" }, ...pr.polja_za_izbor.filter((p) => poljaUska.includes(p.polje)).map(redPolja));
  const osveziOblik = () => { deoSiroka.hidden = !siroka.checked; deoUska.hidden = siroka.checked; };
  siroka.addEventListener("change", osveziOblik);
  uska.addEventListener("change", osveziOblik);
  osveziOblik();

  const posalji = h("button", { type: "submit", class: "dugme" }, "Dodaj i proveri");
  const nazad = h("button", { type: "button", class: "dugme dugme--tiho", onclick: () => korakFajl() }, "Nazad");
  const forma = $("dijalog-forma");
  forma.onsubmit = async (e) => {
    e.preventDefault();
    posalji.disabled = true;
    const polja = {};
    for (const [polje, sel] of Object.entries(izbori)) {
      if (sel.value && (!siroka.checked || !poljaUska.includes(polje))) polja[polje] = sel.value;
    }
    const izabrane = siroka.checked ? Object.values(kvadratici).filter((cb) => cb.checked).map((cb) => cb.value) : null;
    try {
      const r = await api("/api/izvori", {
        putanja: pr.putanja, model: model.value.trim(), polja, kolone: izabrane,
        istorijski: istorijski.checked, redosled_datuma: md.checked ? "md" : "dm",
      });
      $("dijalog").close();
      const iz = r.izvestaj;
      let tekst = `Učitano ${broj(iz.novih_rezultata, 0)} ${mnozina(iz.novih_rezultata, ["rezultat", "rezultata", "rezultata"])}, `
        + `${iz.novih_alarma} ${mnozina(iz.novih_alarma, ["problem", "problema", "problema"])}.`;
      if (iz.greske.length) tekst += ` ${iz.greske.join(" ")}`;
      obavesti(tekst, iz.greske.length > 0);
      await osvezi();
    } catch (greska) {
      posalji.disabled = false;
      korakPotvrda(greska.message);
    }
  };

  const opseg = pr.od ? `${vremeGodina(Date.parse(pr.od))} – ${vremeGodina(Date.parse(pr.do))}` : "vreme nije prepoznato";
  $("dijalog-telo").replaceChildren(...[
    h("p", { class: "dijalog__uvod" },
      h("strong", null, pr.fajl.split("/").pop()), `: ${broj(pr.redova, 0)} ${mnozina(pr.redova, ["red", "reda", "redova"])}, ${opseg}.`),
    greska ? h("p", { class: "dijalog__greska", role: "alert" }, greska) : null,
    pr.upozorenja.length ? h("ul", { class: "dijalog__upozorenja" }, pr.upozorenja.map((u) => h("li", null, u))) : null,
    h("div", { class: "polja" },
      h("label", { class: "polje" }, h("span", null, "Naziv modela"), model),
      ...poljaSvuda.map(redPolja)),
    h("fieldset", { class: "oblik" },
      h("legend", null, "Kako je zapisan rezultat modela?"),
      h("label", null, uska, " u jednoj koloni"),
      h("label", null, siroka, " u više kolona, svaka je poseban izvor")),
    deoUska,
    deoSiroka,
    pr.kolone.some((k) => k.primeri.some((v) => /\d\/\d/.test(v))) ? h("fieldset", { class: "oblik" },
      h("legend", null, "Datumi sa kosim crtama: šta je prvo?"),
      h("label", null, dm, " dan pa mesec (11/10 = 11. oktobar)"),
      h("label", null, md, " mesec pa dan (11/10 = 10. novembar)")) : null,
    h("label", { class: "polje polje--kvadratic" }, istorijski,
      h("span", null, "Ovo su stari podaci (proba ili arhiva)",
        h("span", { class: "polje__malo" }, pr.istorijski
          ? ` Poslednji rezultat je od ${vremeGodina(Date.parse(pr.do))}, pa se vreme računa od njega. Inače bi pisalo da podaci ne stižu.`
          : " Za fajl koji model i dalje dopunjava ostavite prazno."))),
    h("div", { class: "dijalog__dugmad" }, nazad, posalji),
  ].filter(Boolean));
  model.focus();
}

// ---------------------------------------------------------------------------
// Izbor, filteri, osvežavanje
// ---------------------------------------------------------------------------


async function proveriSada() {
  const dugme = $("proveri");
  dugme.disabled = true;
  dugme.textContent = "Proveravam…";
  try {
    const iz = await api("/api/nadzor", {});
    let tekst = `Provera je završena: ${iz.novih_rezultata} ${mnozina(iz.novih_rezultata, ["nov rezultat", "nova rezultata", "novih rezultata"])}, `
      + `${iz.novih_alarma} ${mnozina(iz.novih_alarma, ["nov problem", "nova problema", "novih problema"])}.`;
    if (iz.greske.length) tekst += ` Problemi: ${iz.greske.join(" ")}`;
    obavesti(tekst, iz.greske.length > 0);
    await osvezi();
  } catch (e) {
    obavesti(e.message, true);
  } finally {
    dugme.disabled = false;
    dugme.textContent = "Proveri sada";
  }
}

// ---------------------------------------------------------------------------

/** Probni podaci: model "odjednom" pogreši, pa se odmah vidi alarm i mejl. */
async function napraviProblem() {
  const dugme = $("demo-dugme");
  dugme.disabled = true;
  dugme.textContent = "Pravim…";
  try {
    const r = await api("/api/demo/problem", { vrsta: $("demo-vrsta").value });
    const iz = r.izvestaj;
    const mejlGreska = iz.greske.find((g) => g.includes("mejl"));
    let tekst = `${r.opis} Provera: ${iz.novih_alarma} ${mnozina(iz.novih_alarma, ["nov problem", "nova problema", "novih problema"])}.`;
    if (!iz.novih_alarma) tekst += " (Isti problem je već prijavljen pre manje od 10 minuta, pa se ne šalje ponovo.)";
    else if (mejlGreska) tekst += ` Mejl nije poslat: ${mejlGreska.split(": ").slice(1).join(": ")}`;
    else if (iz.poslato_mejlom) tekst += " Mejl je poslat, pogledaj sanduče.";
    else tekst += " Mejl nije poslat jer obaveštenja mejlom nisu uključena (deo ispod).";
    $("demo-rezultat").textContent = tekst;
    obavesti(mejlGreska ? "Problem je napravljen, ali mejl nije poslat." : "Problem je napravljen.", Boolean(mejlGreska));
    await osvezi();
  } catch (e) {
    obavesti(e.message, true);
  } finally {
    dugme.disabled = false;
    dugme.textContent = "Napravi problem sada";
  }
}

// ---------------------------------------------------------------------------
// Obaveštenja mejlom
// ---------------------------------------------------------------------------

/** Popunjava formu iz podešavanja. Lozinka nikad ne stiže sa servera, samo da li postoji. */
function popuniMejl(m) {
  $("mejl-ukljuceno").checked = m.ukljuceno;
  $("mejl-odmah").checked = m.odmah;
  $("mejl-dnevni").checked = m.dnevni;
  $("mejl-sat").value = m.dnevni_sat;
  $("mejl-za").value = m.za.join("\n");
  $("mejl-server").value = m.server;
  $("mejl-port").value = m.port;
  $("mejl-korisnik").value = m.korisnik;
  $("mejl-adresa").value = m.adresa_aplikacije ?? "";
  $("mejl-lozinka").value = "";
  $("mejl-lozinka").placeholder = m.lozinka_sacuvana ? "••••••••  (sačuvana; prazno = ostaje ista)" : "";
  const opis = $("mejl-lozinka-opis");
  if (m.lozinka_iz_okruzenja) {
    opis.replaceChildren("Lozinka se uzima iz promenljive okruženja MONITORING_MEJL_LOZINKA (ima prednost).");
  } else if (m.lozinka_sacuvana) {
    opis.replaceChildren("Lozinka je sačuvana šifrovana i ne prikazuje se. ",
      h("button", { type: "button", class: "veza", onclick: zaboraviLozinku }, "Zaboravi lozinku"));
  } else {
    opis.replaceChildren("Čuva se šifrovana, samo na ovom računaru, i posle se više ne prikazuje.");
  }
  let stanje;
  if (!m.ukljuceno) stanje = "Isključeno. Problemi se vide samo na stranici.";
  else {
    const sta = [m.odmah ? "odmah za nove probleme" : null, m.dnevni ? `dnevni pregled u ${m.dnevni_sat}` : null].filter(Boolean);
    stanje = `Uključeno: ${sta.join(" i ") || "ništa nije izabrano"}, na ${m.za.length} ${mnozina(m.za.length, ["adresu", "adrese", "adresa"])}.`;
    if (m.dnevni_poslat) {
      const [d, v] = m.dnevni_poslat.split("T");
      stanje += ` Poslednji dnevni pregled: ${d.split("-").reverse().join(".")}.${v ? ` u ${v.slice(0, 5)}` : ""}.`;
    }
  }
  $("mejl-stanje").textContent = stanje;
  const g = $("mejl-greska");
  g.hidden = !m.greska;
  g.textContent = m.greska ? `Poslednje slanje nije uspelo: ${m.greska}` : "";
}

function izForme() {
  return {
    ukljuceno: $("mejl-ukljuceno").checked,
    odmah: $("mejl-odmah").checked,
    dnevni: $("mejl-dnevni").checked,
    dnevni_sat: $("mejl-sat").value || "07:30",
    za: $("mejl-za").value.split(/[\n,;]+/).map((x) => x.trim()).filter(Boolean),
    server: $("mejl-server").value.trim(),
    port: Number($("mejl-port").value) || 587,
    korisnik: $("mejl-korisnik").value.trim(),
    od: "",
    adresa_aplikacije: $("mejl-adresa").value.trim() || null,
    lozinka: $("mejl-lozinka").value || null,
  };
}

async function sacuvajMejl() {
  const m = await api("/api/mejl", izForme());
  popuniMejl(m);
  return m;
}

async function zaboraviLozinku() {
  if (!confirm("Obrisati sačuvanu lozinku? Mejlovi neće moći da se šalju dok se ne upiše nova.")) return;
  try {
    popuniMejl(await api("/api/mejl/lozinka", null, "DELETE"));
    obavesti("Lozinka je obrisana.");
  } catch (e) {
    obavesti(e.message, true);
  }
}

function pokreniMejl() {
  $("mejl-gmail").addEventListener("click", () => { $("mejl-server").value = "smtp.gmail.com"; $("mejl-port").value = 587; $("mejl-korisnik").focus(); });
  $("mejl-outlook").addEventListener("click", () => { $("mejl-server").value = "smtp.office365.com"; $("mejl-port").value = 587; $("mejl-korisnik").focus(); });
  $("mejl-forma").addEventListener("submit", async (e) => {
    e.preventDefault();
    const dugme = $("mejl-sacuvaj");
    dugme.disabled = true;
    try {
      await sacuvajMejl();
      obavesti("Podešavanja mejla su sačuvana.");
    } catch (greska) {
      obavesti(greska.message, true);
    } finally {
      dugme.disabled = false;
    }
  });
  // Prekidač "Uključeno" se čuva odmah, da se ne zaboravi Sačuvaj.
  $("mejl-ukljuceno").addEventListener("change", async (e) => {
    try {
      await sacuvajMejl();
      obavesti(e.target.checked ? "Mejl je uključen." : "Mejl je isključen.");
    } catch (greska) {
      e.target.checked = !e.target.checked;
      obavesti(greska.message, true);
    }
  });
  $("mejl-proba").addEventListener("click", async (e) => {
    const dugme = e.currentTarget;
    dugme.disabled = true;
    dugme.textContent = "Šaljem…";
    try {
      await sacuvajMejl(); // proba ide sa onim što piše u formi
      const r = await api("/api/mejl/proba", {});
      obavesti(r.poruka);
      $("mejl-greska").hidden = true;
    } catch (greska) {
      $("mejl-greska").hidden = false;
      $("mejl-greska").textContent = greska.message;
    } finally {
      dugme.disabled = false;
      dugme.textContent = "Pošalji probni mejl";
    }
  });
}

function pokreni() {
  pokreniMejl();
  api("/api/mejl").then(popuniMejl).catch((e) => obavesti(e.message, true));
  $("proveri").addEventListener("click", proveriSada);
  $("demo-dugme").addEventListener("click", napraviProblem);
  $("dodaj").addEventListener("click", otvoriDodavanje);
  $("dijalog-zatvori").addEventListener("click", () => $("dijalog").close());
  osvezi();
}

pokreni();
