/*
 * Zajedničke pomoćne funkcije za obe stranice (pregled i podešavanja):
 * pravljenje elemenata, vreme i brojevi u srpskom zapisu, razgovor sa
 * serverom, oblačić i obaveštenja.
 *
 * Sav tekst iz podataka (imena, opisi) ubacuje se kao TEKST, nikad kao
 * HTML. Tako ni čudno ime modela ne može da izvrši kod.
 */

export const DAN = 86400000;
export const SAT = 3600000;
export const MINUT = 60000;
export const SEKUND = 1000;

export const $ = (id) => document.getElementById(id);

/** Pravi HTML element. Tekst iz podataka uvek ide kao tekst, nikad kao HTML. */
export function h(oznaka, svojstva, ...deca) {
  const el = document.createElement(oznaka);
  for (const [k, v] of Object.entries(svojstva || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const d of deca.flat()) {
    if (d == null || d === false) continue;
    el.append(d instanceof Node ? d : document.createTextNode(String(d)));
  }
  return el;
}

/** Pravi SVG element (deo grafikona). */
export function s(oznaka, atributi, roditelj) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", oznaka);
  for (const [k, v] of Object.entries(atributi || {})) {
    if (v != null) el.setAttribute(k, typeof v === "number" ? +v.toFixed(2) : v);
  }
  if (roditelj) roditelj.append(el);
  return el;
}

export function svgTekst(roditelj, x, y, tekst, klasa, sidro = "start") {
  const t = s("text", { x, y, class: klasa, "text-anchor": sidro }, roditelj);
  t.textContent = tekst;
  return t;
}
export function zapamti(kljuc, vrednost) {
  try { localStorage.setItem(`monitoring.${kljuc}`, JSON.stringify(vrednost)); } catch { /* nije bitno */ }
}

export function seti(kljuc, podrazumevano) {
  try {
    const v = localStorage.getItem(`monitoring.${kljuc}`);
    return v == null ? podrazumevano : JSON.parse(v);
  } catch {
    return podrazumevano;
  }
}
// --- vreme, po zoni iz konfiguracije ---

let formatVremena = null;

export function postaviZonu(zona) {
  if (formatVremena && formatVremena.resolvedOptions().timeZone === zona) return;
  formatVremena = new Intl.DateTimeFormat("sr-Latn-RS", {
    timeZone: zona, hourCycle: "h23", year: "numeric", month: "2-digit",
    day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

export function delovi(ms) {
  const d = {};
  for (const p of formatVremena.formatToParts(new Date(ms))) d[p.type] = p.value;
  return d;
}

/** Koliko je lokalno vreme (u zoni iz konfiguracije) ispred UTC-a, u milisekundama. */
export function ofset(ms) {
  const d = delovi(ms);
  return Date.UTC(+d.year, +d.month - 1, +d.day, +d.hour, +d.minute, +d.second) - Math.floor(ms / 1000) * 1000;
}

export const ovaGodina = String(new Date().getFullYear());
// Godina se piše samo kad nije tekuća (stari podaci), da ne smeta u svakodnevnom radu.
export const datum = (ms) => { const d = delovi(ms); return `${+d.day}.${+d.month}.${d.year === ovaGodina ? "" : `${d.year}.`}`; };
export const satMinut = (ms) => { const d = delovi(ms); return `${d.hour}:${d.minute}`; };
export const vreme = (ms) => `${datum(ms)} ${satMinut(ms)}`;
export const vremeGodina = (ms) => { const d = delovi(ms); return `${+d.day}.${+d.month}.${d.year}. ${d.hour}:${d.minute}`; };
export const vremeSekunde = (ms) => { const d = delovi(ms); return `${d.hour}:${d.minute}:${d.second}`; };
export function raspon(od, doo) {
  // Celi dani (od ponoći do ponoći): samo datumi, bez "00:00–00:00".
  if (satMinut(od) === "00:00" && satMinut(doo) === "00:00" && doo - od >= DAN - SAT) {
    return datum(od) === datum(doo - 1) ? datum(od) : `${datum(od)} – ${datum(doo - 1)}`;
  }
  return datum(od) === datum(doo - 1) ? `${datum(od)} ${satMinut(od)}–${satMinut(doo)}`
    : `${vreme(od)} – ${vreme(doo)}`;
}

// --- brojevi, srpski zapis (1.234,5) ---

const formatiBrojeva = new Map();

export function broj(x, decimala) {
  let f = formatiBrojeva.get(decimala);
  if (!f) {
    f = new Intl.NumberFormat("sr-Latn-RS", { minimumFractionDigits: decimala, maximumFractionDigits: decimala });
    formatiBrojeva.set(decimala, f);
  }
  return f.format(x).replace("-", "\u2212"); // pravi znak minus, ne crtica
}

/** Koliko decimala: oko tri cifre (63,5 / 1.235 / 0,53). */
export const decimale = (a) => { if (Number.isInteger(a)) return 0; a = Math.abs(a); return a >= 100 || a === 0 ? 0 : a >= 1 ? 1 : a >= 0.1 ? 2 : 3; };

export function saJedinicom(x, jedinica, kao) {
  return broj(x, decimale(kao ?? x)) + (jedinica ? ` ${jedinica}` : "");
}

export function saZnakom(x, jedinica, kao) {
  const dec = decimale(kao ?? x);
  const r = Number(x.toFixed(dec));
  return (r > 0 ? "+" : "") + broj(r === 0 ? 0 : r, dec) + (jedinica ? ` ${jedinica}` : "");
}

export const procenat = (udeo) => `${broj(udeo * 100, 0)}%`;

export function mnozina(n, [jedan, dva, pet]) {
  const d = n % 10, s100 = n % 100;
  if (d === 1 && s100 !== 11) return jedan;
  if (d >= 2 && d <= 4 && (s100 < 12 || s100 > 14)) return dva;
  return pet;
}

export function trajanje(ms) {
  if (ms < MINUT) return `${broj(ms / SEKUND, ms < 10 * SEKUND && ms % SEKUND ? 1 : 0)} s`;
  const min = Math.round(ms / 60000);
  if (min < 60) return `${min} min`;
  const sati = ms / SAT;
  if (sati < 48) return `${broj(sati, Number.isInteger(+sati.toFixed(1)) ? 0 : 1)} h`;
  const dana = Math.round(ms / DAN);
  return `${dana} ${mnozina(dana, ["dan", "dana", "dana"])}`;
}

export function starost(sekundi) {
  if (sekundi < 90) return "upravo";
  if (sekundi < 3600) return `pre ${Math.round(sekundi / 60)} min`;
  if (sekundi < 48 * 3600) return `pre ${Math.round(sekundi / 3600)} h`;
  return `pre ${Math.round(sekundi / 86400)} dana`;
}
// ---------------------------------------------------------------------------
// Razgovor sa serverom
// ---------------------------------------------------------------------------

export async function api(putanja, telo, metod = null) {
  const opcije = { headers: { Accept: "application/json" } };
  if (metod) {
    opcije.method = metod;
    opcije.headers["X-Dashboard"] = "1";
  } else if (telo !== undefined) {
    opcije.method = "POST";
    // Bez ovog zaglavlja server odbija svaku izmenu (zaštita od CSRF).
    opcije.headers["X-Dashboard"] = "1";
    opcije.headers["Content-Type"] = "application/json";
    opcije.body = JSON.stringify(telo);
  }
  let odgovor;
  try {
    odgovor = await fetch(putanja, opcije);
  } catch {
    throw new Error("Server ne odgovara. Proverite da li je dashboard još pokrenut u Terminalu.");
  }
  if (!odgovor.ok) {
    let poruka = `Server je vratio grešku ${odgovor.status}.`;
    try {
      const j = await odgovor.json();
      if (typeof j.detail === "string") poruka = j.detail;
      else if (Array.isArray(j.detail)) poruka = "Proverite uneta polja.";
    } catch { /* odgovor nije JSON */ }
    throw new Error(poruka);
  }
  return odgovor.json();
}

// ---------------------------------------------------------------------------
// Oblačić (tooltip) i obaveštenja
// ---------------------------------------------------------------------------

export function prikaziOblacic(sadrzaj, x, y) {
  const el = $("tooltip");
  el.replaceChildren(...sadrzaj);
  el.hidden = false;
  const r = el.getBoundingClientRect();
  let levo = x + 14, gore = y + 14;
  if (levo + r.width > innerWidth - 8) levo = x - r.width - 14;
  if (gore + r.height > innerHeight - 8) gore = y - r.height - 14;
  el.style.left = `${Math.max(8, levo)}px`;
  el.style.top = `${Math.max(8, gore)}px`;
}

export const sakrijOblacic = () => { $("tooltip").hidden = true; };

export const naslovOblacica = (tekst) => h("p", { class: "tooltip__naslov" }, tekst);

/** Jedan red oblačića: vrednost je jača, ime je slabije (čitalac već zna seriju, traži broj). */
export function redOblacica(kljuc, vrednost, ime) {
  let znak;
  if (kljuc instanceof Node) znak = kljuc;
  else znak = h("span", { class: kljuc ? `tooltip__kljuc k-${kljuc}` : "tooltip__kljuc" });
  return h("div", { class: "tooltip__red" }, znak,
    h("span", { class: "tooltip__vrednost" }, vrednost), ime ? h("span", { class: "tooltip__ime" }, ime) : null);
}

let tajmerObavestenja;

export function obavesti(tekst, greska = false) {
  const el = $("obavestenje");
  el.textContent = tekst;
  el.className = `obavestenje${greska ? " obavestenje--greska" : ""}`;
  el.hidden = false;
  clearTimeout(tajmerObavestenja);
  tajmerObavestenja = setTimeout(() => { el.hidden = true; }, greska ? 9000 : 5000);
}
