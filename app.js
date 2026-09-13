/*
 * Primäre Datenquelle:
 * Ein lokaler Export aus nodegoat. Der Bearer-Token bleibt dadurch
 * ausserhalb des Browsers und wird nie an Besucher*innen ausgeliefert.
 */
const SITE_DATA_URL = "data/site-data.json";

/*
 * Nur als Fallback während der Umstellung.
 * Sobald site-data.json vorhanden ist, werden diese Dateien nicht
 * mehr für die Website-Daten verwendet.
 */
const DATA_URL = "data/geocoded.json";
const GV_METADATA_URL = "data/gv-metadata.json";

const EUROPE_CENTER = [50.3, 9.5];
const EUROPE_ZOOM = 4;

let allRecords = [];
let gvMetadata = {};
let gvOrder = [];
let dataSource = "legacy";

/*
 * Personenindex wird einmal beim Laden aufgebaut.
 * Dadurch müssen wir die gesamten Quelldaten beim Filtern und Öffnen
 * eines Profils nicht immer wieder neu durchsuchen.
 */
let personIndex = new Map();
let personOrder = [];
let currentPersonKey = null;

let personMap = null;
let personMarkerLayer = null;

let sharesTypeChart = null;
let sharesConcentrationChart = null;
let sharesEntityChart = null;
let sharesClassificationCountChart = null;
let sharesClassificationSharesChart = null;
let sharesChartsConfigured = false;

let currentGvId = null;
let currentGvRecords = [];
let currentDetailIndex = 0;

let gvMap = null;
let gvMarkerLayer = null;

/*
 * Quellenviewer der Generalversammlungen.
 * OpenSeadragon unterstützt echte IIIF Image API info.json-Dateien
 * und als Fallback normale lokale Rasterbilder.
 */
let gvSourceViewer = null;
let gvSourcePages = [];
let currentGvSourceIndex = 0;
let sourceJsonRequestToken = 0;

let panoramaViewer = null;
let panoramaReady = false;
let latestPanoramaToken = 0;


/* =========================================================
   HILFSFUNKTIONEN
   ========================================================= */

function parseNumber(value) {
  const cleaned = String(value ?? "")
    .trim()
    .replace(/[^\d.-]/g, "");

  return cleaned ? Number(cleaned) : 0;
}


function formatNumber(value) {
  return new Intl.NumberFormat("de-CH").format(
    parseNumber(value)
  );
}


function hasCoordinates(record) {
  return (
    Number.isFinite(Number(record.lat)) &&
    Number.isFinite(Number(record.lon))
  );
}


function actionsTotal(record) {
  if (
    record &&
    record.actions_total !== undefined &&
    record.actions_total !== null &&
    String(record.actions_total).trim() !== ""
  ) {
    return parseNumber(
      record.actions_total
    );
  }

  return (
    parseNumber(record?.actions_o) +
    parseNumber(record?.actions_p)
  );
}


function setText(id, value) {
  const element = document.getElementById(id);

  if (element) {
    element.textContent = value;
  }
}


function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}


function qualityLabel(value) {
  return ({
    exact_address: "genaue Adresse",
    locality: "nur Ort",
    unreviewed: "ungeprüft",
    unreviewed_address: "ungeprüft",
    nodegoat: "nodegoat",
    missing: "keine Adresse"
  })[value] || value || "ungeprüft";
}


function gvSortValue(gvId) {
  const info = gvMetadata[gvId] || {};

  if (info.date) {
    return info.date;
  }

  return `${String(info.year || "9999").padStart(4, "0")}-99-99`;
}


function recordsForGv(gvId) {
  return allRecords.filter(
    record => record.gv_id === gvId
  );
}


function sourceLabel(filename) {
  return filename || "Unbekannte Quelldatei";
}


function gvDisplayDate(info) {
  if (!info) return "";

  if (info.date) {
    const [year, month, day] = info.date.split("-");

    if (year && month && day) {
      return `${day}.${month}.${year}`;
    }
  }

  if (info.year) {
    return String(info.year);
  }

  return "";
}


/*
 * Liest das historische Jahr unabhängig davon aus,
 * ob gv-metadata.json ein Feld "year" oder "date" verwendet.
 */
function metadataYear(info) {
  if (!info) {
    return null;
  }

  const explicitYear = Number(info.year);

  if (
    Number.isInteger(explicitYear) &&
    explicitYear > 0
  ) {
    return explicitYear;
  }

  const match = String(
    info.date || ""
  ).match(/^(\d{4})/);

  return match
    ? Number(match[1])
    : null;
}


/*
 * Findet die Generalversammlung eines Jahres dynamisch.
 * Keine internen gv_ids müssen im HTML eingetragen werden.
 */
function gvIdForYear(year) {
  const targetYear = Number(year);

  const matches = gvOrder.filter(
    gvId => {
      const info = gvMetadata[gvId] || {};

      return (
        metadataYear(info) === targetYear &&
        recordsForGv(gvId).length > 0
      );
    }
  );

  return matches[0] || null;
}


function updatePrimaryNavigation(viewId) {
  const researchButton = document.getElementById(
    "researchPageButton"
  );

  const corpusButton = document.getElementById(
    "corpusPageButton"
  );

  const nodegoatButton = document.getElementById(
    "nodegoatPageButton"
  );

  const researchActive = viewId === "researchView";
  const corpusActive = [
    "homeView",
    "personView",
    "gvView",
    "detailView"
  ].includes(viewId);
  const nodegoatActive = viewId === "nodegoatView";

  if (researchButton) {
    researchButton.classList.toggle(
      "active",
      researchActive
    );

    researchButton.setAttribute(
      "aria-pressed",
      String(researchActive)
    );
  }

  if (corpusButton) {
    corpusButton.classList.toggle(
      "active",
      corpusActive
    );

    corpusButton.setAttribute(
      "aria-pressed",
      String(corpusActive)
    );
  }

  if (nodegoatButton) {
    nodegoatButton.classList.toggle(
      "active",
      nodegoatActive
    );

    nodegoatButton.setAttribute(
      "aria-pressed",
      String(nodegoatActive)
    );
  }
}


function showOnly(viewId) {
  [
    "researchView",
    "homeView",
    "nodegoatView",
    "personView",
    "gvView",
    "detailView"
  ].forEach(id => {
    const element = document.getElementById(id);

    if (element) {
      element.classList.toggle(
        "hidden",
        id !== viewId
      );
    }
  });

  updatePrimaryNavigation(viewId);

  window.scrollTo({
    top: 0,
    behavior: "instant"
  });
}


function renderResearch() {
  showOnly("researchView");
}


function renderNodegoat() {
  showOnly("nodegoatView");
}


function enterResearch() {
  const landingScreen = document.getElementById(
    "landingScreen"
  );

  const siteContent = document.getElementById(
    "siteContent"
  );

  document.body.classList.remove(
    "landing-active"
  );

  if (siteContent) {
    siteContent.removeAttribute(
      "aria-hidden"
    );
  }

  renderResearch();

  if (!landingScreen) {
    return;
  }

  landingScreen.classList.add(
    "leaving"
  );

  window.setTimeout(() => {
    landingScreen.classList.add(
      "hidden"
    );
  }, 560);
}


/* =========================================================
   ENTITY RESOLUTION / PERSONENINDEX
   ========================================================= */

/*
 * Bei nodegoat-Exporten wird ausschliesslich die stabile person_id
 * als Identität verwendet. Damit übernimmt die Website direkt die in
 * nodegoat bereits durchgeführte Normalisierung / Entity Resolution.
 *
 * Die folgenden Namensfunktionen bleiben nur als Fallback für die
 * alten lokalen JSON-Dateien erhalten, falls site-data.json fehlt.
 */
const PERSON_KEY_ALIASES = new Map([
  ["pani terenzino", "pani terenzio"]
]);

const PERSON_DISPLAY_NAMES = new Map([
  ["pani terenzio", "Terenzio PANI"],
  ["alain breham", "Alain BREHAM"],
  ["breham alain", "Alain BREHAM"],
  ["breham marc", "Marc BREHAM"],
  ["marc breham", "Marc BREHAM"]
]);


function cleanEntityName(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(
      /^(mr|m|mme|mlle|monsieur|madame|me)\.?\s+/i,
      ""
    )
    .replace(/[()[\],.;:]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}


function rawPersonKey(value) {
  const cleaned = cleanEntityName(value)
    .toLocaleLowerCase("de");

  if (!cleaned) {
    return "";
  }

  return cleaned
    .split(/\s+/)
    .filter(Boolean)
    .sort((a, b) => a.localeCompare(b, "de"))
    .join(" ");
}


function personKeyForRecord(record) {
  /*
   * Falls der Datensatz später eine stabile nodegoat-/Personen-ID
   * erhält, wird diese automatisch bevorzugt.
   */
  const stableId =
    record.person_id ||
    record.entity_id ||
    record.nodegoat_object_id ||
    record.object_id;

  if (stableId) {
    return `id:${stableId}`;
  }

  let key = rawPersonKey(
    record.name
  );

  /*
   * Alias-Mapping arbeitet direkt mit dem bereits normalisierten,
   * alphabetisch sortierten Schlüssel.
   */
  key =
    PERSON_KEY_ALIASES.get(key) ||
    key;

  return key;
}


function preferredEntityName(records, key) {
  const nodegoatName =
    records.find(
      record => record.normalized_name
    )?.normalized_name;

  if (nodegoatName) {
    return nodegoatName;
  }

  const explicit =
    PERSON_DISPLAY_NAMES.get(key);

  if (explicit) {
    return explicit;
  }

  const cleanedNames = records
    .map(record => cleanEntityName(record.name))
    .filter(Boolean);

  if (!cleanedNames.length) {
    return "Ohne Namen";
  }

  /*
   * Kürzere bereinigte Form bevorzugen; bei gleicher Länge
   * alphabetisch. Dadurch verschwinden Titel wie Mr/Mme,
   * ohne historische Information zu erfinden.
   */
  cleanedNames.sort((a, b) => {
    if (a.length !== b.length) {
      return a.length - b.length;
    }

    return a.localeCompare(b, "de");
  });

  return cleanedNames[0];
}



/* =========================================================
   KLASSIFIKATION DER HISTORISCHEN AKTEUR*INNEN
   ========================================================= */

/*
 * Die Klassifikation stammt direkt aus dem nodegoat-Export:
 *
 * W = weiblich
 * M = männlich
 * F = Firma
 * U = unklar
 *
 * Ein fehlender Wert wird NICHT automatisch als U interpretiert.
 */
const CLASSIFICATION_ORDER = [
  "W",
  "M",
  "F",
  "U"
];

const CLASSIFICATION_LABELS = {
  W: "weiblich",
  M: "männlich",
  F: "Firma",
  U: "unklar"
};

const CLASSIFICATION_CHART_LABELS = {
  W: "Frauen",
  M: "Männer",
  F: "Firmen",
  U: "unklar"
};

const CLASSIFICATION_COLORS = {
  W: {
    background: "rgba(190, 157, 192, 0.78)",
    border: "rgba(220, 194, 222, 1)"
  },
  M: {
    background: "rgba(111, 166, 184, 0.78)",
    border: "rgba(157, 201, 214, 1)"
  },
  F: {
    background: "rgba(221, 190, 122, 0.78)",
    border: "rgba(239, 216, 164, 1)"
  },
  U: {
    background: "rgba(174, 180, 174, 0.58)",
    border: "rgba(205, 211, 205, 0.9)"
  }
};


function classificationCode(value) {
  const code = String(
    value ?? ""
  )
    .trim()
    .toUpperCase();

  return CLASSIFICATION_ORDER.includes(code)
    ? code
    : "";
}


function classificationForRecord(record) {
  return classificationCode(
    record?.classification_code
  );
}


function classificationLabel(code) {
  return (
    CLASSIFICATION_LABELS[
      classificationCode(code)
    ] ||
    "nicht klassifiziert"
  );
}


function classificationProfileLabel(code) {
  const normalized =
    classificationCode(code);

  if (!normalized) {
    return "–";
  }

  return (
    `${normalized} · ` +
    `${classificationLabel(normalized)}`
  );
}


function buildPersonIndex() {
  const grouped = new Map();

  for (const record of allRecords) {
    const key = personKeyForRecord(record);

    if (!key) {
      continue;
    }

    let entity = grouped.get(key);

    if (!entity) {
      entity = {
        key,
        records: [],
        names: new Set(),
        addresses: new Set()
      };

      grouped.set(key, entity);
    }

    entity.records.push(record);

    if (record.name) {
      entity.names.add(
        String(record.name).trim()
      );
    }

    if (record.address) {
      entity.addresses.add(
        String(record.address)
          .replace(/\s+/g, " ")
          .trim()
      );
    }
  }

  for (const entity of grouped.values()) {
    entity.records.sort(
      (a, b) => {
        const aValue =
          gvSortValue(a.gv_id);

        const bValue =
          gvSortValue(b.gv_id);

        return aValue.localeCompare(
          bValue
        );
      }
    );

    entity.displayName =
      preferredEntityName(
        entity.records,
        entity.key
      );

    entity.searchText = [
      entity.displayName,
      ...entity.names,
      ...entity.addresses
    ]
      .join(" ")
      .toLocaleLowerCase("de");

    entity.gvCount =
      new Set(
        entity.records.map(
          record => record.gv_id
        )
      ).size;

    entity.maxShares =
      entity.records.reduce(
        (max, record) =>
          Math.max(
            max,
            actionsTotal(record)
          ),
        0
      );

    const classificationCodes = [
      ...new Set(
        entity.records
          .map(classificationForRecord)
          .filter(Boolean)
      )
    ];

    if (classificationCodes.length > 1) {
      console.warn(
        "Widersprüchliche Klassifikation für",
        entity.displayName,
        classificationCodes
      );
    }

    entity.classificationCode =
      classificationCodes[0] || "";

    entity.classificationLabel =
      classificationLabel(
        entity.classificationCode
      );
  }

  personIndex = grouped;

  personOrder = [
    ...grouped.keys()
  ].sort(
    (a, b) =>
      grouped
        .get(a)
        .displayName
        .localeCompare(
          grouped.get(b).displayName,
          "de"
        )
  );
}


function personYear(record) {
  return metadataYear(
    gvMetadata[
      record.gv_id
    ] || {}
  );
}


function distinctPersonAddresses(entity) {
  return [
    ...entity.addresses
  ].filter(Boolean);
}


/* =========================================================
   FORSCHUNGSWORKFLOW: JAHRE → GENERALVERSAMMLUNGEN
   ========================================================= */

function showWorkflowYearMessage(text) {
  const element = document.getElementById(
    "workflowYearMessage"
  );

  if (!element) {
    return;
  }

  if (!text) {
    element.textContent = "";
    element.classList.add("hidden");
    return;
  }

  element.textContent = text;
  element.classList.remove("hidden");
}


function openWorkflowYear(year) {
  const gvId = gvIdForYear(year);

  if (!gvId) {
    showWorkflowYearMessage(
      `Für ${year} wurde keine passende Generalversammlung gefunden.`
    );

    console.warn(
      "Keine Generalversammlung für Workflow-Jahr:",
      year
    );

    return;
  }

  showWorkflowYearMessage("");
  openGv(gvId);
}


/* =========================================================
   STARTSEITE
   ========================================================= */

function setCorpusMode(mode) {
  const gvPanel = document.getElementById("gvCorpusPanel");
  const personPanel = document.getElementById("personCorpusPanel");
  const sharesPanel = document.getElementById("sharesCorpusPanel");

  const gvButton = document.getElementById("showGvCorpusButton");
  const personButton = document.getElementById("showPersonCorpusButton");
  const sharesButton = document.getElementById("showSharesCorpusButton");

  const peopleActive = mode === "people";
  const sharesActive = mode === "shares";
  const gvActive = !peopleActive && !sharesActive;

  gvPanel?.classList.toggle("hidden", !gvActive);
  personPanel?.classList.toggle("hidden", !peopleActive);
  sharesPanel?.classList.toggle("hidden", !sharesActive);

  gvButton?.classList.toggle("active", gvActive);
  personButton?.classList.toggle("active", peopleActive);
  sharesButton?.classList.toggle("active", sharesActive);

  gvButton?.setAttribute("aria-pressed", String(gvActive));
  personButton?.setAttribute("aria-pressed", String(peopleActive));
  sharesButton?.setAttribute("aria-pressed", String(sharesActive));

  if (peopleActive) {
    renderPersonCards();
  }

  if (sharesActive) {
    renderShareVisualisations();
  }
}

function renderHome(
  mode = "gv"
) {
  showOnly("homeView");

  const cards =
    document.getElementById(
      "gvCards"
    );

  cards.innerHTML = "";

  const totalGeocoded =
    allRecords.filter(
      hasCoordinates
    ).length;

  setText(
    "corpusSummary",
    `${gvOrder.length} Generalversammlungen · ` +
    `${allRecords.length} historische Snapshots · ` +
    `${totalGeocoded} georeferenziert · ` +
    `${
      dataSource === "nodegoat"
        ? "Datenquelle: nodegoat"
        : "Datenquelle: lokaler Fallback"
    }`
  );

  gvOrder.forEach(gvId => {
    const info =
      gvMetadata[gvId];

    const records =
      recordsForGv(gvId);

    const geocodedCount =
      records.filter(
        hasCoordinates
      ).length;

    const totalShares =
      records.reduce(
        (sum, record) =>
          sum + actionsTotal(record),
        0
      );

    const button =
      document.createElement(
        "button"
      );

    button.type = "button";
    button.className = "gv-card";

    button.innerHTML = `
      <span class="gv-card-date">
        ${escapeHtml(
          gvDisplayDate(info)
        )}
      </span>

      <strong>
        ${escapeHtml(
          info.title || gvId
        )}
      </strong>

      <span class="gv-card-meta">
        ${records.length} Anwesende
      </span>

      <span class="gv-card-meta">
        ${formatNumber(totalShares)} Aktien
      </span>

      <span class="gv-card-meta">
        ${geocodedCount} Wohnorte georeferenziert
      </span>

      <span class="gv-card-action">
        Generalversammlung öffnen →
      </span>
    `;

    button.addEventListener(
      "click",
      () => openGv(gvId)
    );

    cards.appendChild(
      button
    );
  });

  setCorpusMode(mode);
}


/* =========================================================
   AKTIENENTWICKLUNG
   ========================================================= */

function configureShareCharts() {
  if (sharesChartsConfigured || typeof Chart === "undefined") {
    return;
  }

  /*
   * Nur Text-Defaults global setzen.
   * Dataset-Farben werden pro Diagramm explizit definiert,
   * damit sie auf dem dunklen Hintergrund gut sichtbar bleiben.
   */
  Chart.defaults.color = "rgba(243, 240, 233, 0.78)";
  Chart.defaults.font.family = "Arial, Helvetica, sans-serif";

  sharesChartsConfigured = true;
}


function destroyShareChart(chart) {
  if (!chart) return null;
  chart.destroy();
  return null;
}


function shareGvLabel(gvId) {
  const info = gvMetadata[gvId] || {};
  return metadataYear(info) || gvDisplayDate(info) || gvId;
}


function metadataShareNumber(value) {
  if (
    value === undefined ||
    value === null ||
    String(value).trim() === ""
  ) {
    return null;
  }

  const number = Number(value);

  return Number.isFinite(number)
    ? number
    : null;
}


function shareTotalsForGv(gvId) {
  /*
   * Für GV-Gesamtsummen sind die expliziten Felder des
   * Generalversammlungsobjekts die bessere Referenz als das
   * erneute Addieren sämtlicher Personen-Snapshots.
   *
   * Das verhindert insbesondere, dass ein zweifelhafter Einzelwert
   * die gesamte Diagrammskala verzerrt.
   */
  const info = gvMetadata[gvId] || {};

  const metadataO =
    metadataShareNumber(
      info.total_actions_o
    );

  const metadataP =
    metadataShareNumber(
      info.total_actions_p
    );

  const metadataTotal =
    metadataShareNumber(
      info.total_actions
    );

  if (
    metadataO !== null ||
    metadataP !== null ||
    metadataTotal !== null
  ) {
    let ordinaires =
      metadataO ?? 0;

    let priorite =
      metadataP ?? 0;

    if (
      metadataO === null &&
      metadataTotal !== null &&
      metadataP !== null
    ) {
      ordinaires =
        Math.max(
          metadataTotal -
          metadataP,
          0
        );
    }

    if (
      metadataP === null &&
      metadataTotal !== null &&
      metadataO !== null
    ) {
      priorite =
        Math.max(
          metadataTotal -
          metadataO,
          0
        );
    }

    const total =
      metadataTotal ??
      (
        ordinaires +
        priorite
      );

    return {
      ordinaires,
      priorite,
      total,
      source: "gv_metadata"
    };
  }

  /*
   * Fallback nur für Datensätze ohne GV-Summen.
   */
  const records =
    recordsForGv(gvId);

  const ordinaires =
    records.reduce(
      (sum, record) =>
        sum +
        parseNumber(
          record.actions_o
        ),
      0
    );

  const priorite =
    records.reduce(
      (sum, record) =>
        sum +
        parseNumber(
          record.actions_p
        ),
      0
    );

  return {
    ordinaires,
    priorite,
    total:
      ordinaires +
      priorite,
    source:
      "records"
  };
}


function analysisHoldingForRecord(
  record,
  gvId
) {
  const value =
    actionsTotal(
      record
    );

  if (
    !Number.isFinite(value) ||
    value <= 0
  ) {
    return null;
  }

  const gvTotal =
    shareTotalsForGv(
      gvId
    ).total;

  /*
   * Ein einzelner Aktienbestand kann logisch nicht grösser sein
   * als der gesamte in der GV dokumentierte Aktienbestand.
   *
   * Solche Werte werden NICHT automatisch korrigiert, sondern
   * als Datenqualitätsproblem aus der quantitativen Analyse
   * ausgeschlossen.
   */
  if (
    Number.isFinite(gvTotal) &&
    gvTotal > 0 &&
    value > gvTotal
  ) {
    return null;
  }

  return value;
}


function shareDataQualityIssues() {
  const issues = [];

  gvOrder.forEach(
    gvId => {
      const totals =
        shareTotalsForGv(
          gvId
        );

      if (
        !totals.total ||
        totals.total <= 0
      ) {
        return;
      }

      recordsForGv(gvId)
        .forEach(
          record => {
            const value =
              actionsTotal(
                record
              );

            if (
              Number.isFinite(value) &&
              value >
                totals.total
            ) {
              issues.push({
                gvId,
                year:
                  shareGvLabel(
                    gvId
                  ),
                name:
                  record.name ||
                  record.person_name ||
                  "Unbekannte Entität",
                value,
                gvTotal:
                  totals.total
              });
            }
          }
        );
    }
  );

  return issues;
}


function renderShareDataQuality() {
  const element =
    document.getElementById(
      "sharesDataQuality"
    );

  if (!element) {
    return;
  }

  const issues =
    shareDataQualityIssues();

  if (!issues.length) {
    element.innerHTML = "";
    element.classList.add(
      "hidden"
    );
    return;
  }

  const examples =
    issues
      .slice(0, 3)
      .map(
        issue =>
          `<li>` +
          `<strong>${escapeHtml(issue.year)}</strong>: ` +
          `${escapeHtml(issue.name)} – ` +
          `${formatNumber(issue.value)} Aktien ` +
          `(GV-Gesamt: ${formatNumber(issue.gvTotal)})` +
          `</li>`
      )
      .join("");

  element.innerHTML = `
    <div class="shares-data-quality-heading">
      <span>!</span>
      <div>
        <small>Datenqualitätsprüfung</small>
        <strong>
          ${issues.length}
          ${issues.length === 1 ? "auffälliger Einzelwert" : "auffällige Einzelwerte"}
          nicht in Analyseberechnungen verwendet
        </strong>
      </div>
    </div>

    <p>
      Ein einzelner Aktienbestand darf nicht grösser sein als der
      dokumentierte Gesamtbestand derselben Generalversammlung.
      Solche Werte werden nicht automatisch interpretiert oder korrigiert,
      sondern für die Diagrammberechnung ausgeschlossen und sollten in
      Quelle bzw. nodegoat geprüft werden.
    </p>

    <ul>${examples}</ul>
  `;

  element.classList.remove(
    "hidden"
  );
}


function rankedHoldingsForGv(gvId) {
  const gvTotal = shareTotalsForGv(gvId).total;

  return recordsForGv(gvId)
    .map(record => {
      const total = analysisHoldingForRecord(record, gvId);
      if (total === null) return null;

      return {
        key: personKeyForRecord(record),
        name: record.name || record.person_name || "Unbekannte Entität",
        total,
        ordinaires: parseNumber(record.actions_o),
        priorite: parseNumber(record.actions_p),
        sharePercent:
          Number.isFinite(gvTotal) && gvTotal > 0
            ? total / gvTotal * 100
            : null
      };
    })
    .filter(item => item && Number.isFinite(item.total) && item.total > 0)
    .sort((a, b) => b.total - a.total);
}


function summarizeTopHoldings(items, count) {
  const slice = items.slice(0, count);
  const total = slice.reduce((sum, item) => sum + item.total, 0);
  return {
    count: slice.length,
    items: slice,
    total
  };
}


function concentrationForGv(gvId) {
  const ranked = rankedHoldingsForGv(gvId);

  const gvTotal =
    shareTotalsForGv(
      gvId
    ).total;

  const denominator =
    (
      Number.isFinite(gvTotal) &&
      gvTotal > 0
    )
      ? gvTotal
      : ranked.reduce(
          (sum, item) =>
            sum + item.total,
          0
        );

  const shareOfTopN = count => {
    if (!denominator) {
      return 0;
    }

    const amount = ranked
      .slice(0, count)
      .reduce((sum, item) => sum + item.total, 0);

    return amount / denominator * 100;
  };

  return {
    largest: shareOfTopN(1),
    top3: shareOfTopN(3),
    top5: shareOfTopN(5),
    gvTotal: denominator,
    ranked,
    largestInfo: summarizeTopHoldings(ranked, 1),
    top3Info: summarizeTopHoldings(ranked, 3),
    top5Info: summarizeTopHoldings(ranked, 5)
  };
}


function concentrationDetailList(items) {
  if (!items.length) {
    return '<li>Keine auswertbaren Aktienbestände vorhanden.</li>';
  }

  return items.map((item, index) => `
    <li>
      <span class="shares-concentration-rank">${index + 1}.</span>

      ${
        item.key && personIndex.has(item.key)
          ? `
            <button
              type="button"
              class="shares-concentration-person-link"
              data-person-key="${escapeHtml(item.key)}"
              title="Profil von ${escapeHtml(item.name)} öffnen"
            >
              ${escapeHtml(item.name)}
              <span aria-hidden="true">→</span>
            </button>
          `
          : `
            <span class="shares-concentration-name">
              ${escapeHtml(item.name)}
            </span>
          `
      }

      <span class="shares-concentration-total">${formatNumber(item.total)} Aktien</span>
    </li>
  `).join('');
}


function renderShareConcentrationDetails(index) {
  const container = document.getElementById('sharesConcentrationDetails');
  if (!container) return;

  const safeIndex = Math.max(0, Math.min(index ?? 0, gvOrder.length - 1));
  const gvId = gvOrder[safeIndex];
  const gvLabel = shareGvLabel(gvId);
  const details = concentrationForGv(gvId);

  container.innerHTML = `
    <div class="shares-concentration-header">
      <div>
        <small>Detailansicht zur markierten Generalversammlung</small>
        <h4>${escapeHtml(gvLabel)}</h4>
      </div>
      <div class="shares-concentration-totalbox">
        <small>Dokumentierter Gesamtbestand</small>
        <strong>${formatNumber(details.gvTotal)} Aktien</strong>
      </div>
    </div>

    <div class="shares-concentration-grid">
      <section class="shares-concentration-card">
        <div class="shares-concentration-card-head">
          <small>Grösster Aktienbestand</small>
          <strong>${details.largest.toFixed(1)} %</strong>
        </div>
        <p>${details.largestInfo.count ? 'Grösster dokumentierter Einzelbestand dieser GV.' : 'Keine Daten vorhanden.'}</p>
        <ol>${concentrationDetailList(details.largestInfo.items)}</ol>
      </section>

      <section class="shares-concentration-card">
        <div class="shares-concentration-card-head">
          <small>Top 3</small>
          <strong>${details.top3.toFixed(1)} %</strong>
        </div>
        <p>
          Zusammen ${formatNumber(details.top3Info.total)} Aktien
          ${details.top3Info.count ? `· ${details.top3Info.count} ${details.top3Info.count === 1 ? 'Akteur*in' : 'Akteur*innen'}` : ''}
        </p>
        <ol>${concentrationDetailList(details.top3Info.items)}</ol>
      </section>

      <section class="shares-concentration-card">
        <div class="shares-concentration-card-head">
          <small>Top 5</small>
          <strong>${details.top5.toFixed(1)} %</strong>
        </div>
        <p>
          Zusammen ${formatNumber(details.top5Info.total)} Aktien
          ${details.top5Info.count ? `· ${details.top5Info.count} ${details.top5Info.count === 1 ? 'Akteur*in' : 'Akteur*innen'}` : ''}
        </p>
        <ol>${concentrationDetailList(details.top5Info.items)}</ol>
      </section>
    </div>
  `;

  container
    .querySelectorAll(
      ".shares-concentration-person-link"
    )
    .forEach(button => {
      button.addEventListener(
        "click",
        () => {
          const key =
            button.dataset.personKey;

          if (!key) {
            return;
          }

          openPersonProfile(key);
        }
      );
    });
}


function renderShareTypeChart() {
  const canvas = document.getElementById("sharesTypeChart");

  if (!canvas || typeof Chart === "undefined") return;

  sharesTypeChart = destroyShareChart(sharesTypeChart);

  const labels = gvOrder.map(shareGvLabel);
  const totals = gvOrder.map(shareTotalsForGv);

  sharesTypeChart = new Chart(canvas, {
    type: "bar",

    data: {
      labels,
      datasets: [
        {
          label: "Aktien Ordinaires",
          data: totals.map(value => value.ordinaires),
          stack: "shares",
          backgroundColor: "rgba(221, 190, 122, 0.78)",
          borderColor: "rgba(239, 216, 164, 1)",
          borderWidth: 1
        },
        {
          label: "Aktien Priorité",
          data: totals.map(value => value.priorite),
          stack: "shares",
          backgroundColor: "rgba(111, 166, 184, 0.78)",
          borderColor: "rgba(157, 201, 214, 1)",
          borderWidth: 1
        }
      ]
    },

    options: {
      responsive: true,
      maintainAspectRatio: false,

      interaction: {
        mode: "index",
        intersect: false
      },

      plugins: {
        legend: {
          position: "bottom"
        },

        tooltip: {
          callbacks: {
            footer(items) {
              const index = items?.[0]?.dataIndex;
              if (index === undefined) return "";

              return "Gesamt: " + formatNumber(totals[index].total);
            }
          }
        }
      },

      scales: {
        x: {
          stacked: true,
          grid: {
            color: "rgba(243, 240, 233, 0.08)"
          },
          title: {
            display: true,
            text: "Generalversammlung"
          }
        },

        y: {
          stacked: true,
          beginAtZero: true,
          grid: {
            color: "rgba(243, 240, 233, 0.08)"
          },
          title: {
            display: true,
            text: "Dokumentierte Aktien"
          }
        }
      }
    }
  });
}


function renderShareConcentrationChart() {
  const canvas = document.getElementById("sharesConcentrationChart");

  if (!canvas || typeof Chart === "undefined") return;

  sharesConcentrationChart =
    destroyShareChart(sharesConcentrationChart);

  const labels = gvOrder.map(shareGvLabel);
  const concentration = gvOrder.map(concentrationForGv);

  sharesConcentrationChart = new Chart(canvas, {
    type: "line",

    data: {
      labels,
      datasets: [
        {
          label: "Grösster Aktienbestand",
          data: concentration.map(value => value.largest),
          tension: 0.2,
          borderColor: "rgba(221, 190, 122, 1)",
          backgroundColor: "rgba(221, 190, 122, 0.18)",
          borderWidth: 2.5,
          pointRadius: 4,
          pointHoverRadius: 6
        },
        {
          label: "Top 3",
          data: concentration.map(value => value.top3),
          tension: 0.2,
          borderColor: "rgba(116, 181, 156, 1)",
          backgroundColor: "rgba(116, 181, 156, 0.18)",
          borderWidth: 2.5,
          pointRadius: 4,
          pointHoverRadius: 6
        },
        {
          label: "Top 5",
          data: concentration.map(value => value.top5),
          tension: 0.2,
          borderColor: "rgba(157, 201, 214, 1)",
          backgroundColor: "rgba(157, 201, 214, 0.18)",
          borderWidth: 2.5,
          pointRadius: 4,
          pointHoverRadius: 6
        }
      ]
    },

    options: {
      responsive: true,
      maintainAspectRatio: false,

      interaction: {
        mode: "index",
        intersect: false
      },

      onHover(event, activeElements, chart) {
        if (activeElements?.length) {
          renderShareConcentrationDetails(activeElements[0].index);
        }
      },

      onClick(event, activeElements, chart) {
        if (activeElements?.length) {
          renderShareConcentrationDetails(activeElements[0].index);
        }
      },

      plugins: {
        legend: {
          position: "bottom"
        },

        tooltip: {
          callbacks: {
            label(context) {
              return (
                `${context.dataset.label}: ` +
                `${context.parsed.y.toFixed(1)} %`
              );
            }
          }
        }
      },

      scales: {
        x: {
          grid: {
            color: "rgba(243, 240, 233, 0.08)"
          }
        },
        y: {
          beginAtZero: true,
          max: 100,
          grid: {
            color: "rgba(243, 240, 233, 0.08)"
          },

          title: {
            display: true,
            text: "Anteil an dokumentierten Aktien (%)"
          },

          ticks: {
            callback(value) {
              return `${value} %`;
            }
          }
        }
      }
    }
  });

  renderShareConcentrationDetails(Math.max(gvOrder.length - 1, 0));
}


function shareEntityDefaultKey() {
  if (!personOrder.length) return "";

  return [...personOrder].sort((a, b) => {
    const entityA = personIndex.get(a);
    const entityB = personIndex.get(b);

    if (entityA.gvCount !== entityB.gvCount) {
      return entityB.gvCount - entityA.gvCount;
    }

    return entityB.maxShares - entityA.maxShares;
  })[0];
}


function populateShareEntitySelect() {
  const select = document.getElementById("sharesEntitySelect");
  if (!select) return;

  const previous = select.value;
  select.innerHTML = "";

  const fragment = document.createDocumentFragment();

  personOrder.forEach(key => {
    const entity = personIndex.get(key);
    if (!entity) return;

    const option = document.createElement("option");
    option.value = key;
    option.textContent = `${entity.displayName} · ${entity.gvCount} GV`;
    fragment.appendChild(option);
  });

  select.appendChild(fragment);

  if (previous && personIndex.has(previous)) {
    select.value = previous;
    return;
  }

  const defaultKey = shareEntityDefaultKey();
  if (defaultKey) {
    select.value = defaultKey;
  }
}


function renderShareEntityChart() {
  const canvas = document.getElementById("sharesEntityChart");
  const select = document.getElementById("sharesEntitySelect");
  const note = document.getElementById("sharesEntityNote");

  if (!canvas || !select || typeof Chart === "undefined") return;

  const entity = personIndex.get(select.value);

  sharesEntityChart = destroyShareChart(sharesEntityChart);

  if (!entity) {
    if (note) note.textContent = "Keine Entität ausgewählt.";
    return;
  }

  const byGv = new Map();

  entity.records.forEach(record => {
    const current = byGv.get(record.gv_id) || {
      ordinaires: 0,
      priorite: 0,
      total: 0
    };

    const safeTotal =
      analysisHoldingForRecord(
        record,
        record.gv_id
      );

    /*
     * Auffällige/inkonsistente Werte werden als fehlende
     * Beobachtung behandelt und nicht als 0 eingetragen.
     */
    if (safeTotal === null) {
      return;
    }

    current.ordinaires +=
      parseNumber(
        record.actions_o
      );

    current.priorite +=
      parseNumber(
        record.actions_p
      );

    current.total +=
      safeTotal;

    byGv.set(
      record.gv_id,
      current
    );
  });

  const labels = gvOrder.map(shareGvLabel);

  const ordinaires = gvOrder.map(
    gvId => byGv.has(gvId) ? byGv.get(gvId).ordinaires : null
  );

  const priorite = gvOrder.map(
    gvId => byGv.has(gvId) ? byGv.get(gvId).priorite : null
  );

  const totals = gvOrder.map(
    gvId => byGv.has(gvId) ? byGv.get(gvId).total : null
  );

  sharesEntityChart = new Chart(canvas, {
    type: "line",

    data: {
      labels,
      datasets: [
        {
          label: "Gesamt",
          data: totals,
          tension: 0.15,
          spanGaps: false,
          borderColor: "rgba(243, 240, 233, 1)",
          backgroundColor: "rgba(243, 240, 233, 0.15)",
          borderWidth: 2.8,
          pointRadius: 4,
          pointHoverRadius: 6
        },
        {
          label: "Ordinaires",
          data: ordinaires,
          tension: 0.15,
          spanGaps: false,
          borderColor: "rgba(221, 190, 122, 1)",
          backgroundColor: "rgba(221, 190, 122, 0.15)",
          borderWidth: 2.3,
          pointRadius: 4,
          pointHoverRadius: 6
        },
        {
          label: "Priorité",
          data: priorite,
          tension: 0.15,
          spanGaps: false,
          borderColor: "rgba(157, 201, 214, 1)",
          backgroundColor: "rgba(157, 201, 214, 0.15)",
          borderWidth: 2.3,
          pointRadius: 4,
          pointHoverRadius: 6
        }
      ]
    },

    options: {
      responsive: true,
      maintainAspectRatio: false,

      interaction: {
        mode: "index",
        intersect: false
      },

      plugins: {
        legend: {
          position: "bottom"
        }
      },

      scales: {
        y: {
          beginAtZero: true,
          title: {
            display: true,
            text: "Dokumentierter Aktienbestand"
          }
        }
      }
    }
  });

  if (note) {
    note.textContent =
      `${entity.displayName}: in ${byGv.size} von ` +
      `${gvOrder.length} Generalversammlungen dokumentiert. ` +
      `Nicht belegte GVs werden als Lücke und nicht als 0 dargestellt.`;
  }
}



/* =========================================================
   GESCHLECHT & AKTEUR*INNENTYP
   ========================================================= */

function classificationStatsForGv(gvId) {
  const buckets = Object.fromEntries(
    CLASSIFICATION_ORDER.map(
      code => [
        code,
        {
          actors: new Set(),
          shares: 0
        }
      ]
    )
  );

  for (const record of recordsForGv(gvId)) {
    const code =
      classificationForRecord(record);

    if (!code) {
      continue;
    }

    const key =
      personKeyForRecord(record);

    if (key) {
      buckets[
        code
      ].actors.add(key);
    }

    const holding =
      analysisHoldingForRecord(
        record,
        gvId
      );

    if (holding !== null) {
      buckets[
        code
      ].shares += holding;
    }
  }

  const gvTotal =
    shareTotalsForGv(
      gvId
    ).total;

  const result = {
    gvTotal:
      Number.isFinite(gvTotal)
        ? gvTotal
        : 0
  };

  CLASSIFICATION_ORDER.forEach(
    code => {
      result[
        code
      ] = {
        actors:
          buckets[code].actors.size,
        shares:
          buckets[code].shares,
        sharePercent:
          (
            Number.isFinite(gvTotal) &&
            gvTotal > 0
          )
            ? (
                buckets[code].shares /
                gvTotal *
                100
              )
            : 0
      };
    }
  );

  return result;
}


function classificationCoverage() {
  const result = {
    total: personOrder.length,
    classified: 0,
    missing: 0,
    W: 0,
    M: 0,
    F: 0,
    U: 0
  };

  personOrder.forEach(
    key => {
      const entity =
        personIndex.get(key);

      const code =
        classificationCode(
          entity?.classificationCode
        );

      if (!code) {
        result.missing += 1;
        return;
      }

      result.classified += 1;
      result[code] += 1;
    }
  );

  return result;
}


function renderClassificationCoverage() {
  const element =
    document.getElementById(
      "sharesClassificationCoverage"
    );

  if (!element) {
    return;
  }

  const coverage =
    classificationCoverage();

  if (!coverage.total) {
    element.innerHTML = "";
    element.classList.add(
      "hidden"
    );
    return;
  }

  element.innerHTML = `
    <div class="shares-classification-coverage-head">
      <div>
        <small>Klassifikation aus nodegoat</small>
        <strong>
          ${coverage.classified} von ${coverage.total}
          Akteur*innen mit W / M / F / U versehen
        </strong>
      </div>

      <div class="shares-classification-counts">
        <span><b>W</b> ${coverage.W}</span>
        <span><b>M</b> ${coverage.M}</span>
        <span><b>F</b> ${coverage.F}</span>
        <span><b>U</b> ${coverage.U}</span>
      </div>
    </div>

    <p>
      W = weiblich · M = männlich · F = Firma · U = unklar.
      Firmen werden bewusst als eigene Kategorie behandelt.
      Ein fehlender Wert wird nicht automatisch als «unklar» interpretiert.
      ${
        coverage.missing
          ? `${coverage.missing} Akteur*innen besitzen im analysierten Korpus keinen Klassifikationswert.`
          : "Für alle im analysierten Korpus vorkommenden Akteur*innen liegt ein Klassifikationswert vor."
      }
    </p>
  `;

  element.classList.remove(
    "hidden"
  );
}


function classificationDataset(code, data, stack) {
  return {
    label:
      CLASSIFICATION_CHART_LABELS[
        code
      ],
    data,
    stack,
    backgroundColor:
      CLASSIFICATION_COLORS[
        code
      ].background,
    borderColor:
      CLASSIFICATION_COLORS[
        code
      ].border,
    borderWidth: 1
  };
}


function renderClassificationCountChart() {
  const canvas =
    document.getElementById(
      "sharesClassificationCountChart"
    );

  if (
    !canvas ||
    typeof Chart === "undefined"
  ) {
    return;
  }

  sharesClassificationCountChart =
    destroyShareChart(
      sharesClassificationCountChart
    );

  const labels =
    gvOrder.map(
      shareGvLabel
    );

  const stats =
    gvOrder.map(
      classificationStatsForGv
    );

  sharesClassificationCountChart =
    new Chart(
      canvas,
      {
        type: "bar",

        data: {
          labels,
          datasets:
            CLASSIFICATION_ORDER.map(
              code =>
                classificationDataset(
                  code,
                  stats.map(
                    value =>
                      value[
                        code
                      ].actors
                  ),
                  "classification-actors"
                )
            )
        },

        options: {
          responsive: true,
          maintainAspectRatio: false,

          interaction: {
            mode: "index",
            intersect: false
          },

          plugins: {
            legend: {
              position: "bottom"
            },

            tooltip: {
              callbacks: {
                footer(items) {
                  const index =
                    items?.[0]?.dataIndex;

                  if (
                    index === undefined
                  ) {
                    return "";
                  }

                  const total =
                    CLASSIFICATION_ORDER
                      .reduce(
                        (sum, code) =>
                          sum +
                          stats[index][code]
                            .actors,
                        0
                      );

                  return (
                    "Klassifizierte Akteur*innen: " +
                    formatNumber(total)
                  );
                }
              }
            }
          },

          scales: {
            x: {
              stacked: true,
              grid: {
                color:
                  "rgba(243, 240, 233, 0.08)"
              }
            },

            y: {
              stacked: true,
              beginAtZero: true,
              ticks: {
                precision: 0
              },
              grid: {
                color:
                  "rgba(243, 240, 233, 0.08)"
              },
              title: {
                display: true,
                text:
                  "Dokumentierte Akteur*innen"
              }
            }
          }
        }
      }
    );
}


function renderClassificationSharesChart() {
  const canvas =
    document.getElementById(
      "sharesClassificationSharesChart"
    );

  if (
    !canvas ||
    typeof Chart === "undefined"
  ) {
    return;
  }

  sharesClassificationSharesChart =
    destroyShareChart(
      sharesClassificationSharesChart
    );

  const labels =
    gvOrder.map(
      shareGvLabel
    );

  const stats =
    gvOrder.map(
      classificationStatsForGv
    );

  sharesClassificationSharesChart =
    new Chart(
      canvas,
      {
        type: "bar",

        data: {
          labels,
          datasets:
            CLASSIFICATION_ORDER.map(
              code =>
                classificationDataset(
                  code,
                  stats.map(
                    value =>
                      value[
                        code
                      ].sharePercent
                  ),
                  "classification-shares"
                )
            )
        },

        options: {
          responsive: true,
          maintainAspectRatio: false,

          interaction: {
            mode: "index",
            intersect: false
          },

          plugins: {
            legend: {
              position: "bottom"
            },

            tooltip: {
              callbacks: {
                label(context) {
                  return (
                    `${context.dataset.label}: ` +
                    `${context.parsed.y.toFixed(1)} %`
                  );
                },

                footer(items) {
                  const index =
                    items?.[0]?.dataIndex;

                  if (
                    index === undefined
                  ) {
                    return "";
                  }

                  const included =
                    CLASSIFICATION_ORDER
                      .reduce(
                        (sum, code) =>
                          sum +
                          stats[index][code]
                            .shares,
                        0
                      );

                  return (
                    "Auswertbare klassifizierte Aktien: " +
                    formatNumber(included) +
                    " / " +
                    formatNumber(
                      stats[index].gvTotal
                    )
                  );
                }
              }
            }
          },

          scales: {
            x: {
              stacked: true,
              grid: {
                color:
                  "rgba(243, 240, 233, 0.08)"
              }
            },

            y: {
              stacked: true,
              beginAtZero: true,
              max: 100,
              grid: {
                color:
                  "rgba(243, 240, 233, 0.08)"
              },
              title: {
                display: true,
                text:
                  "Anteil am dokumentierten Aktienbestand (%)"
              },
              ticks: {
                callback(value) {
                  return `${value} %`;
                }
              }
            }
          }
        }
      }
    );
}


function renderShareVisualisations() {
  configureShareCharts();

  if (typeof Chart === "undefined") {
    console.warn("Chart.js wurde nicht geladen.");
    return;
  }

  renderShareDataQuality();
  renderClassificationCoverage();
  populateShareEntitySelect();
  renderShareTypeChart();
  renderClassificationCountChart();
  renderClassificationSharesChart();
  renderShareConcentrationChart();
  renderShareEntityChart();
}




function renderPersonCards() {
  const container =
    document.getElementById(
      "personCards"
    );

  const empty =
    document.getElementById(
      "personEmpty"
    );

  const search =
    document.getElementById(
      "personSearch"
    );

  if (!container) {
    return;
  }

  const query =
    String(
      search?.value || ""
    )
      .trim()
      .toLocaleLowerCase("de");

  const keys =
    query
      ? personOrder.filter(
          key =>
            personIndex
              .get(key)
              .searchText
              .includes(query)
        )
      : personOrder;

  container.innerHTML = "";

  setText(
    "personCorpusSummary",
    `${personOrder.length} ${
      dataSource === "nodegoat"
        ? "nodegoat-Objekte"
        : "zusammengeführte Entitäten"
    }`
  );

  if (!keys.length) {
    empty?.classList.remove(
      "hidden"
    );

    return;
  }

  empty?.classList.add(
    "hidden"
  );

  const fragment =
    document.createDocumentFragment();

  for (const key of keys) {
    const entity =
      personIndex.get(key);

    const years =
      entity.records
        .map(personYear)
        .filter(Boolean);

    const firstYear =
      years.length
        ? Math.min(...years)
        : null;

    const lastYear =
      years.length
        ? Math.max(...years)
        : null;

    const locationCount =
      distinctPersonAddresses(
        entity
      ).length;

    const button =
      document.createElement(
        "button"
      );

    button.type = "button";
    button.className =
      "person-card";

    button.innerHTML = `
      <span class="person-card-kicker">
        Historische Entität
      </span>

      <strong>
        ${escapeHtml(
          entity.displayName
        )}
      </strong>

      <span class="person-card-classification">
        ${escapeHtml(
          entity.classificationLabel
        )}
      </span>

      <span class="person-card-meta">
        ${entity.gvCount}
        ${
          entity.gvCount === 1
            ? "Generalversammlung"
            : "Generalversammlungen"
        }
      </span>

      <span class="person-card-meta">
        ${
          firstYear && lastYear
            ? firstYear === lastYear
              ? String(firstYear)
              : `${firstYear}–${lastYear}`
            : "Zeitraum unbekannt"
        }
      </span>

      <span class="person-card-meta">
        ${locationCount}
        ${
          locationCount === 1
            ? "Wohnort"
            : "Wohnorte"
        }
      </span>

      <span class="person-card-action">
        Profil öffnen →
      </span>
    `;

    button.addEventListener(
      "click",
      () =>
        openPersonProfile(key)
    );

    fragment.appendChild(
      button
    );
  }

  container.appendChild(
    fragment
  );
}


/* =========================================================
   PERSONENPROFIL: WOHNORTKARTE
   ========================================================= */

function normaliseLocationAddress(value) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim();
}


/*
 * Mehrere historische Snapshots desselben Wohnorts werden zu einem
 * Karteneintrag zusammengefasst.
 *
 * Primärer Schlüssel:
 *   Koordinaten auf 5 Dezimalstellen ≈ etwa 1 Meter Genauigkeit.
 *
 * Dadurch wird derselbe georeferenzierte Wohnort nicht mehrfach
 * markiert, wenn er in mehreren Generalversammlungen vorkommt.
 */
function distinctPersonLocations(entity) {
  const locations = new Map();

  for (const record of entity.records) {
    if (!hasCoordinates(record)) {
      continue;
    }

    const lat =
      Number(record.lat);

    const lon =
      Number(record.lon);

    const key =
      `${lat.toFixed(5)},${lon.toFixed(5)}`;

    let location =
      locations.get(key);

    if (!location) {
      location = {
        key,
        lat,
        lon,
        address:
          normaliseLocationAddress(
            record.address
          ) ||
          "Wohnort ohne Adressangabe",
        records: []
      };

      locations.set(
        key,
        location
      );
    }

    /*
     * Falls der erste Snapshot keine Adresse hatte, später aber
     * eine vorhanden ist, übernehmen wir die aussagekräftigere Form.
     */
    const address =
      normaliseLocationAddress(
        record.address
      );

    if (
      address &&
      (
        !location.address ||
        location.address ===
          "Wohnort ohne Adressangabe"
      )
    ) {
      location.address =
        address;
    }

    location.records.push(
      record
    );
  }

  const result =
    [...locations.values()];

  for (const location of result) {
    location.records.sort(
      (a, b) =>
        gvSortValue(a.gv_id)
          .localeCompare(
            gvSortValue(b.gv_id)
          )
    );

    location.years = [
      ...new Set(
        location.records
          .map(personYear)
          .filter(Boolean)
      )
    ].sort(
      (a, b) => a - b
    );
  }

  return result;
}


function initialisePersonMap() {
  if (personMap) {
    return;
  }

  const element =
    document.getElementById(
      "personMap"
    );

  if (
    !element ||
    typeof L === "undefined"
  ) {
    return;
  }

  personMap = L.map(
    "personMap",
    {
      center: EUROPE_CENTER,
      zoom: EUROPE_ZOOM,
      minZoom: 2
    }
  );

  L.tileLayer(
    "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">' +
        "OpenStreetMap-Mitwirkende</a>"
    }
  ).addTo(
    personMap
  );
}


function renderPersonMap(entity) {
  initialisePersonMap();

  if (!personMap) {
    return;
  }

  const locations =
    distinctPersonLocations(
      entity
    );

  setText(
    "personMapSummary",
    `${locations.length} ${
      locations.length === 1
        ? "georeferenzierter Wohnort"
        : "georeferenzierte Wohnorte"
    }`
  );

  if (personMarkerLayer) {
    personMap.removeLayer(
      personMarkerLayer
    );
  }

  personMarkerLayer =
    L.layerGroup();

  const bounds = [];

  for (const location of locations) {
    const yearsText =
      location.years.length
        ? location.years.join(" · ")
        : "Jahr unbekannt";

    const gvLinks =
      location.records
        .map(record => {
          const info =
            gvMetadata[
              record.gv_id
            ] || {};

          return escapeHtml(
            gvDisplayDate(info) ||
            String(
              personYear(record) ||
              ""
            )
          );
        })
        .filter(Boolean)
        .join(" · ");

    const marker = L.marker([
      location.lat,
      location.lon
    ]);

    marker.bindPopup(`
      <div class="map-popup person-map-popup">
        <strong>
          ${escapeHtml(
            location.address
          )}
        </strong>

        <span>
          Dokumentiert:
          ${escapeHtml(
            yearsText
          )}
        </span>

        ${
          gvLinks
            ? `<span>GV: ${gvLinks}</span>`
            : ""
        }
      </div>
    `);

    marker.addTo(
      personMarkerLayer
    );

    bounds.push([
      location.lat,
      location.lon
    ]);
  }

  personMarkerLayer.addTo(
    personMap
  );

  /*
   * Leaflet braucht nach dem Wechsel von einer hidden View
   * eine Neuberechnung der Kartengrösse.
   */
  window.setTimeout(
    () => {
      personMap.invalidateSize();

      if (bounds.length === 0) {
        personMap.setView(
          EUROPE_CENTER,
          EUROPE_ZOOM
        );

      } else if (
        bounds.length === 1
      ) {
        personMap.setView(
          bounds[0],
          14
        );

      } else {
        personMap.fitBounds(
          bounds,
          {
            padding: [36, 36],
            maxZoom: 14
          }
        );
      }
    },
    60
  );
}


function openPersonProfile(key) {
  if (!personIndex.has(key)) {
    return;
  }

  currentPersonKey = key;

  showOnly("personView");

  renderPersonProfile();
}


function renderPersonProfile() {
  const entity =
    personIndex.get(
      currentPersonKey
    );

  if (!entity) {
    return;
  }

  const years =
    entity.records
      .map(personYear)
      .filter(Boolean);

  const firstYear =
    years.length
      ? Math.min(...years)
      : null;

  const lastYear =
    years.length
      ? Math.max(...years)
      : null;

  const addresses =
    distinctPersonAddresses(
      entity
    );

  setText(
    "personProfileName",
    entity.displayName
  );

  setText(
    "personProfileClassification",
    classificationProfileLabel(
      entity.classificationCode
    )
  );

  const variants = [
    ...entity.names
  ]
    .filter(
      name =>
        cleanEntityName(name) !==
        entity.displayName
    )
    .sort(
      (a, b) =>
        a.localeCompare(b, "de")
    );

  setText(
    "personProfileVariants",
    variants.length
      ? `Quellenvarianten: ${variants.join(" · ")}`
      : ""
  );

  setText(
    "personProfilePeriod",
    firstYear && lastYear
      ? firstYear === lastYear
        ? String(firstYear)
        : `${firstYear} — ${lastYear}`
      : ""
  );

  setText(
    "personProfileGvCount",
    formatNumber(
      entity.gvCount
    )
  );

  setText(
    "personProfileFirstYear",
    firstYear || "–"
  );

  setText(
    "personProfileLastYear",
    lastYear || "–"
  );

  setText(
    "personProfileMaxShares",
    formatNumber(
      entity.maxShares
    )
  );

  setText(
    "personProfileLocationCount",
    formatNumber(
      addresses.length
    )
  );

  renderPersonTimeline(
    entity
  );

  renderPersonMap(
    entity
  );
}


function renderPersonTimeline(entity) {
  const timeline =
    document.getElementById(
      "personTimeline"
    );

  if (!timeline) {
    return;
  }

  timeline.innerHTML = "";

  const maxShares =
    Math.max(
      1,
      ...entity.records.map(
        actionsTotal
      )
    );

  const fragment =
    document.createDocumentFragment();

  entity.records.forEach(
    record => {
      const info =
        gvMetadata[
          record.gv_id
        ] || {};

      const total =
        actionsTotal(record);

      const width =
        Math.max(
          2,
          total / maxShares * 100
        );

      const item =
        document.createElement(
          "article"
        );

      item.className =
        "person-timeline-item";

      const address =
        String(
          record.address || ""
        )
          .replace(/\s+/g, " ")
          .trim() ||
        "Keine Wohnadresse überliefert";

      item.innerHTML = `
        <div class="person-timeline-date">
          <span>
            ${escapeHtml(
              gvDisplayDate(info)
            )}
          </span>

          <small>
            Generalversammlung
          </small>
        </div>

        <div class="person-timeline-main">
          <h3>
            ${escapeHtml(
              info.title ||
              record.gv_id
            )}
          </h3>

          <p class="person-timeline-address">
            ${escapeHtml(address)}
          </p>

          <div class="person-share-bar">
            <span
              style="width: ${width.toFixed(2)}%"
              aria-hidden="true"
            ></span>
          </div>

          <div class="person-share-values">
            <span>
              Ordinaire
              <strong>
                ${formatNumber(
                  record.actions_o
                )}
              </strong>
            </span>

            <span>
              Priorité
              <strong>
                ${formatNumber(
                  record.actions_p
                )}
              </strong>
            </span>

            <span>
              Total
              <strong>
                ${formatNumber(total)}
              </strong>
            </span>
          </div>
        </div>

        <div class="person-timeline-actions">
          <button
            type="button"
            class="person-gv-button"
          >
            GV öffnen →
          </button>

          <button
            type="button"
            class="person-location-button"
            ${hasCoordinates(record) ? "" : "disabled"}
          >
            Wohnort öffnen →
          </button>
        </div>
      `;

      item
        .querySelector(
          ".person-gv-button"
        )
        .addEventListener(
          "click",
          () =>
            openGv(
              record.gv_id
            )
        );

      item
        .querySelector(
          ".person-location-button"
        )
        .addEventListener(
          "click",
          () =>
            openRecordDetail(
              record
            )
        );

      fragment.appendChild(
        item
      );
    }
  );

  timeline.appendChild(
    fragment
  );
}


function openRecordDetail(record) {
  currentGvId =
    record.gv_id;

  currentGvRecords =
    recordsForGv(
      currentGvId
    );

  currentGvRecords.sort(
    (a, b) => {
      const numberA =
        parseNumber(a.number);

      const numberB =
        parseNumber(b.number);

      if (
        numberA !== numberB
      ) {
        return numberA - numberB;
      }

      return String(
        a.name || ""
      ).localeCompare(
        String(
          b.name || ""
        ),
        "de"
      );
    }
  );

  const index =
    currentGvRecords.indexOf(
      record
    );

  if (index >= 0) {
    openDetail(index);
  }
}



/* =========================================================
   GV-ÜBERSICHT
   ========================================================= */

function openGv(gvId) {
  if (!gvMetadata[gvId]) {
    console.warn(
      "Unbekannte Generalversammlung:",
      gvId
    );
    return;
  }

  currentGvId = gvId;
  currentDetailIndex = 0;

  currentGvRecords = recordsForGv(gvId);

  currentGvRecords.sort((a, b) => {
    const numberA = parseNumber(a.number);
    const numberB = parseNumber(b.number);

    if (numberA !== numberB) {
      return numberA - numberB;
    }

    return String(a.name || "").localeCompare(
      String(b.name || ""),
      "de"
    );
  });

  renderGv();
}


function renderGv() {
  showOnly("gvView");

  const info = gvMetadata[currentGvId] || {};

  setText(
    "gvTitle",
    info.title || currentGvId
  );

  const dateText = gvDisplayDate(info);

  setText(
    "gvDate",
    dateText ? `Historisches Datum: ${dateText}` : ""
  );

  /*
   * Für die Summenkarten ebenfalls die expliziten GV-Gesamtsummen
   * verwenden. So verzerrt ein problematischer Einzelwert die
   * Übersicht einer Generalversammlung nicht.
   */
  const gvShareTotals =
    shareTotalsForGv(
      currentGvId
    );

  const totalO =
    gvShareTotals.ordinaires;

  const totalP =
    gvShareTotals.priorite;

  const geocoded = currentGvRecords.filter(
    hasCoordinates
  ).length;

  setText(
    "gvAttendance",
    formatNumber(currentGvRecords.length)
  );

  setText(
    "gvActionsO",
    formatNumber(totalO)
  );

  setText(
    "gvActionsP",
    formatNumber(totalP)
  );

  setText(
    "gvActionsTotal",
    formatNumber(totalO + totalP)
  );

  setText(
    "gvGeocoded",
    `${geocoded} / ${currentGvRecords.length}`
  );

  renderSources(info);
  renderSourceExplorer(info);
  renderShareholderTable(currentGvRecords);

  document.getElementById(
    "shareholderSearch"
  ).value = "";

  window.setTimeout(
    renderGvMap,
    0
  );
}


function renderSources(info) {
  const list = document.getElementById(
    "gvSources"
  );

  list.innerHTML = "";

  const files = info.source_files || [];

  if (!files.length) {
    const li = document.createElement("li");
    li.textContent = "Keine Quelldatei eingetragen.";
    list.appendChild(li);
    return;
  }

  files.forEach(filename => {
    const li = document.createElement("li");

    li.innerHTML = `
      <span class="source-file">
        ${escapeHtml(sourceLabel(filename))}
      </span>
    `;

    list.appendChild(li);
  });
}


/* =========================================================
   GV: ORIGINALQUELLE + JSON
   ========================================================= */

function sourcePageLabel(page, index) {
  return (
    page.label ||
    page.document ||
    `Quelle ${index + 1}`
  );
}


function destroyGvSourceViewer() {
  if (!gvSourceViewer) {
    return;
  }

  try {
    gvSourceViewer.destroy();
  } catch (error) {
    console.warn(
      "IIIF-Viewer konnte nicht vollständig zerstört werden:",
      error
    );
  }

  gvSourceViewer = null;

  /*
   * OpenSeadragon schreibt eigene Elemente in den Container.
   * Nach destroy() leeren wir ihn zusätzlich, damit eine neue
   * GV garantiert mit einem frischen Viewer startet.
   */
  const element =
    document.getElementById(
      "gvSourceViewer"
    );

  if (element) {
    element.innerHTML = "";
  }
}


function tileSourceForPage(
  page
) {
  if (
    page &&
    page.iiif_info_url
  ) {
    return page.iiif_info_url;
  }

  if (
    page &&
    page.image_url
  ) {
    return {
      type: "image",
      url: page.image_url
    };
  }

  return null;
}


function createGvSourceViewer(
  page
) {
  /*
   * Eine neue Generalversammlung erhält immer einen
   * vollständig neuen OpenSeadragon-Viewer.
   */
  destroyGvSourceViewer();

  const element =
    document.getElementById(
      "gvSourceViewer"
    );

  const tileSource =
    tileSourceForPage(
      page
    );

  if (
    !element ||
    typeof OpenSeadragon ===
      "undefined" ||
    !tileSource
  ) {
    return null;
  }

  /*
   * Wichtig:
   * Die erste Quelle wird bereits bei der Konstruktion als
   * tileSources übergeben. Es gibt für die erste GV-Seite
   * KEIN nachträgliches viewer.open() und keinen simulierten Klick.
   */
  gvSourceViewer =
    OpenSeadragon({
      id: "gvSourceViewer",

      tileSources: [
        tileSource
      ],

      prefixUrl:
        "https://cdn.jsdelivr.net/npm/openseadragon@4.1.0/" +
        "build/openseadragon/images/",

      showNavigator: true,
      navigatorPosition: "BOTTOM_RIGHT",

      showRotationControl: false,
      showFullPageControl: true,
      showHomeControl: true,
      showZoomControl: true,

      gestureSettingsMouse: {
        clickToZoom: false,
        dblClickToZoom: true,
        scrollToZoom: true
      },

      animationTime: 0.8,
      blendTime: 0.15,
      constrainDuringPan: true,
      visibilityRatio: 0.5
    });

  gvSourceViewer.addHandler(
    "open-failed",
    event => {
      console.error(
        "IIIF-Quelle konnte nicht geöffnet werden:",
        event
      );

      setSourceViewerMessage(
        "Die historische Originalquelle konnte nicht geladen werden."
      );
    }
  );

  return gvSourceViewer;
}


function ensureGvSourceViewer(
  page = null
) {
  if (gvSourceViewer) {
    return gvSourceViewer;
  }

  return createGvSourceViewer(
    page
  );
}

function setSourceViewerMessage(
  text
) {
  const message =
    document.getElementById(
      "gvSourceViewerMessage"
    );

  if (!message) {
    return;
  }

  if (!text) {
    message.textContent = "";
    message.classList.add(
      "hidden"
    );

    return;
  }

  message.textContent = text;

  message.classList.remove(
    "hidden"
  );
}


function setSourceExternalLink(
  elementId,
  url,
  label
) {
  const element =
    document.getElementById(
      elementId
    );

  if (!element) {
    return;
  }

  if (!url) {
    element.removeAttribute(
      "href"
    );
    element.classList.add(
      "hidden"
    );
    return;
  }

  element.href = url;
  element.textContent = label;
  element.classList.remove(
    "hidden"
  );
}


async function renderSourceJson(
  page
) {
  const target =
    document.getElementById(
      "gvSourceJson"
    );

  if (!target) {
    return;
  }

  const token =
    ++sourceJsonRequestToken;

  const code =
    target.querySelector(
      "code"
    ) || target;

  const url =
    page?.json_url;

  if (!url) {
    code.textContent =
      "Für diese Quellenseite wurde keine JSON-Datei gefunden.";

    setSourceExternalLink(
      "gvSourceJsonLink",
      "",
      ""
    );

    return;
  }

  setSourceExternalLink(
    "gvSourceJsonLink",
    url,
    "JSON öffnen ↗"
  );

  code.textContent =
    "JSON wird geladen …";

  try {
    const response =
      await fetch(
        url,
        {
          cache: "no-store"
        }
      );

    if (!response.ok) {
      throw new Error(
        `HTTP ${response.status}`
      );
    }

    const data =
      await response.json();

    if (
      token !==
      sourceJsonRequestToken
    ) {
      return;
    }

    code.textContent =
      JSON.stringify(
        data,
        null,
        2
      );

  } catch (error) {
    if (
      token !==
      sourceJsonRequestToken
    ) {
      return;
    }

    console.warn(
      "Quellen-JSON konnte nicht geladen werden:",
      url,
      error
    );

    code.textContent =
      "Die JSON-Datei konnte nicht geladen werden.\n\n" +
      String(
        error.message ||
        error
      );
  }

  target.scrollTop = 0;
}


function updateGvSourcePageUi(
  page,
  index
) {
  currentGvSourceIndex =
    index;

  document
    .querySelectorAll(
      ".source-page-tab"
    )
    .forEach(
      (button, buttonIndex) => {
        const active =
          buttonIndex === index;

        button.classList.toggle(
          "active",
          active
        );

        button.setAttribute(
          "aria-pressed",
          String(active)
        );
      }
    );

  const label =
    sourcePageLabel(
      page,
      index
    );

  setText(
    "gvSourceImageTitle",
    label
  );

  setText(
    "gvSourceJsonTitle",
    page.json_name ||
    "JSON"
  );

  if (page.iiif_info_url) {
    setSourceExternalLink(
      "gvSourceImageLink",
      page.iiif_info_url,
      "IIIF info.json ↗"
    );
  } else if (page.image_url) {
    setSourceExternalLink(
      "gvSourceImageLink",
      page.image_url,
      "Bild öffnen ↗"
    );
  } else {
    setSourceExternalLink(
      "gvSourceImageLink",
      "",
      ""
    );
  }

  renderSourceJson(
    page
  );
}


function openGvSourcePage(
  index
) {
  if (
    index < 0 ||
    index >= gvSourcePages.length
  ) {
    return;
  }

  const page =
    gvSourcePages[index];

  const tileSource =
    tileSourceForPage(
      page
    );

  updateGvSourcePageUi(
    page,
    index
  );

  if (!tileSource) {
    destroyGvSourceViewer();

    setSourceViewerMessage(
      "Für diese Quellenseite wurde noch kein Bild bzw. " +
      "kein IIIF-Service gefunden."
    );

    return;
  }

  setSourceViewerMessage(
    ""
  );

  /*
   * Innerhalb derselben GV wird der bereits bestehende Viewer
   * weiterverwendet. Nur die TileSource wird gewechselt.
   */
  const hadViewer =
    Boolean(
      gvSourceViewer
    );

  const viewer =
    ensureGvSourceViewer(
      page
    );

  if (!viewer) {
    setSourceViewerMessage(
      "Der IIIF-Viewer konnte nicht initialisiert werden."
    );
    return;
  }

  /*
   * Falls bereits ein Viewer für diese GV existiert, wechseln
   * wir nur dessen TileSource. Wurde er gerade neu erzeugt,
   * ist die Quelle bereits über tileSources initialisiert.
   */
  if (hadViewer) {
    viewer.open(
      tileSource
    );
  }
}


function initialiseFirstGvSource() {
  if (!gvSourcePages.length) {
    return;
  }

  const page =
    gvSourcePages[0];

  updateGvSourcePageUi(
    page,
    0
  );

  const tileSource =
    tileSourceForPage(
      page
    );

  if (!tileSource) {
    destroyGvSourceViewer();

    setSourceViewerMessage(
      "Für diese Quellenseite wurde noch kein Bild bzw. " +
      "kein IIIF-Service gefunden."
    );

    return;
  }

  setSourceViewerMessage(
    ""
  );

  /*
   * Kern der neuen Lösung:
   * Die erste Seite wird DIREKT mit dem neuen Viewer konstruiert.
   */
  createGvSourceViewer(
    page
  );
}



function renderSourceExplorer(
  info
) {
  const tabs =
    document.getElementById(
      "gvSourceTabs"
    );

  const workspace =
    document.getElementById(
      "gvSourceWorkspace"
    );

  const empty =
    document.getElementById(
      "gvSourceEmpty"
    );

  if (
    !tabs ||
    !workspace ||
    !empty
  ) {
    return;
  }

  gvSourcePages =
    Array.isArray(
      info.source_pages
    )
      ? info.source_pages
      : [];

  currentGvSourceIndex = 0;
  tabs.innerHTML = "";

  /*
   * Beim Wechsel auf eine andere Generalversammlung wird
   * der komplette Viewer zerstört. Die neue GV erhält danach
   * einen frischen OpenSeadragon-Viewer.
   */
  destroyGvSourceViewer();

  if (!gvSourcePages.length) {
    workspace.classList.add(
      "hidden"
    );

    tabs.classList.add(
      "hidden"
    );

    empty.classList.remove(
      "hidden"
    );

    setText(
      "gvSourceCounter",
      "Keine digitalen Quelldateien verknüpft"
    );

    destroyGvSourceViewer();

    return;
  }

  workspace.classList.remove(
    "hidden"
  );

  tabs.classList.remove(
    "hidden"
  );

  empty.classList.add(
    "hidden"
  );

  setText(
    "gvSourceCounter",
    `${gvSourcePages.length} ${
      gvSourcePages.length === 1
        ? "Quellenseite"
        : "Quellenseiten"
    }`
  );

  const fragment =
    document.createDocumentFragment();

  gvSourcePages.forEach(
    (page, index) => {
      const button =
        document.createElement(
          "button"
        );

      button.type =
        "button";

      button.className =
        "source-page-tab";

      button.setAttribute(
        "aria-pressed",
        String(index === 0)
      );

      button.innerHTML = `
        <span>
          ${String(index + 1).padStart(2, "0")}
        </span>

        <strong>
          ${escapeHtml(
            sourcePageLabel(
              page,
              index
            )
          )}
        </strong>
      `;

      button.addEventListener(
        "click",
        () =>
          openGvSourcePage(
            index
          )
      );

      fragment.appendChild(
        button
      );
    }
  );

  tabs.appendChild(
    fragment
  );

  /*
   * Erste Quelle der GV sofort initialisieren.
   * Kein Timeout, kein requestAnimationFrame, kein simulierter Klick.
   */
  initialiseFirstGvSource();
}


function renderShareholderTable(records) {
  const body = document.getElementById(
    "shareholderTableBody"
  );

  const empty = document.getElementById(
    "shareholderEmpty"
  );

  body.innerHTML = "";

  if (!records.length) {
    empty.classList.remove("hidden");
    return;
  }

  empty.classList.add("hidden");

  records.forEach(record => {
    const realIndex = currentGvRecords.indexOf(
      record
    );

    const row = document.createElement("tr");

    row.className = "clickable-row";
    row.tabIndex = 0;

    row.innerHTML = `
      <td>${escapeHtml(record.number || "–")}</td>

      <td class="name-cell">
        ${escapeHtml(record.name || "Ohne Namen")}
      </td>

      <td>
        ${escapeHtml(
          String(record.address || "")
            .replace(/\s+/g, " ")
            .trim() || "Keine Angabe"
        )}
      </td>

      <td class="number-cell">
        ${formatNumber(record.actions_o)}
      </td>

      <td class="number-cell">
        ${formatNumber(record.actions_p)}
      </td>

      <td class="number-cell total-cell">
        ${formatNumber(actionsTotal(record))}
      </td>
    `;

    const open = () => openDetail(realIndex);

    row.addEventListener(
      "click",
      open
    );

    row.addEventListener(
      "keydown",
      event => {
        if (
          event.key === "Enter" ||
          event.key === " "
        ) {
          event.preventDefault();
          open();
        }
      }
    );

    body.appendChild(row);
  });
}


function filterShareholderTable() {
  const query = document.getElementById(
    "shareholderSearch"
  ).value
    .trim()
    .toLocaleLowerCase("de");

  if (!query) {
    renderShareholderTable(
      currentGvRecords
    );

    return;
  }

  const filtered = currentGvRecords.filter(
    record => {
      const haystack = [
        record.name,
        record.address,
        record.geocode_query,
        record.nominatim_display_name
      ]
        .join(" ")
        .toLocaleLowerCase("de");

      return haystack.includes(query);
    }
  );

  renderShareholderTable(filtered);
}


/* =========================================================
   LEAFLET-KARTE
   ========================================================= */

function initialiseMap() {
  if (gvMap) {
    return;
  }

  gvMap = L.map(
    "gvMap",
    {
      center: EUROPE_CENTER,
      zoom: EUROPE_ZOOM,
      minZoom: 2
    }
  );

  L.tileLayer(
    "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">' +
        "OpenStreetMap-Mitwirkende</a>"
    }
  ).addTo(gvMap);
}


function resetEuropeView() {
  if (!gvMap) return;

  gvMap.setView(
    EUROPE_CENTER,
    EUROPE_ZOOM
  );
}


function renderGvMap() {
  initialiseMap();

  gvMap.invalidateSize();

  if (gvMarkerLayer) {
    gvMap.removeLayer(
      gvMarkerLayer
    );
  }

  gvMarkerLayer = L.markerClusterGroup({
    showCoverageOnHover: false,
    spiderfyOnMaxZoom: true,
    maxClusterRadius: 45
  });

  currentGvRecords.forEach(
    (record, index) => {
      if (!hasCoordinates(record)) {
        return;
      }

      const marker = L.marker([
        Number(record.lat),
        Number(record.lon)
      ]);

      marker.bindPopup(`
        <div class="map-popup">
          <strong>
            ${escapeHtml(record.name || "Ohne Namen")}
          </strong>

          <span>
            ${escapeHtml(
              String(record.address || "")
                .replace(/\s+/g, " ")
                .trim() || "Keine Adressangabe"
            )}
          </span>

          <span>
            ${formatNumber(actionsTotal(record))}
            Aktien total
          </span>

          <button
            type="button"
            class="popup-detail-button"
            data-record-index="${index}"
          >
            Person öffnen →
          </button>
        </div>
      `);

      marker.on(
        "popupopen",
        event => {
          const popupElement =
            event.popup.getElement();

          const button =
            popupElement?.querySelector(
              ".popup-detail-button"
            );

          if (button) {
            button.addEventListener(
              "click",
              () => openDetail(index),
              { once: true }
            );
          }
        }
      );

      gvMarkerLayer.addLayer(
        marker
      );
    }
  );

  gvMarkerLayer.addTo(
    gvMap
  );

  resetEuropeView();
}


/* =========================================================
   DETAILANSICHT
   ========================================================= */

function openDetail(index) {
  if (
    index < 0 ||
    index >= currentGvRecords.length
  ) {
    return;
  }

  currentDetailIndex = index;

  showOnly("detailView");

  renderDetail();
}


function previousDetail() {
  if (!currentGvRecords.length) return;

  currentDetailIndex =
    (
      currentDetailIndex -
      1 +
      currentGvRecords.length
    ) %
    currentGvRecords.length;

  renderDetail();
}


function nextDetail() {
  if (!currentGvRecords.length) return;

  currentDetailIndex =
    (
      currentDetailIndex +
      1
    ) %
    currentGvRecords.length;

  renderDetail();
}


function osmUrl(record) {
  if (hasCoordinates(record)) {
    return (
      "https://www.openstreetmap.org/" +
      `?mlat=${record.lat}` +
      `&mlon=${record.lon}` +
      `#map=18/${record.lat}/${record.lon}`
    );
  }

  return (
    "https://www.openstreetmap.org/search" +
    `?query=${encodeURIComponent(
      record.geocode_query ||
      record.address ||
      ""
    )}`
  );
}


function panoramaxUrl(record) {
  if (!hasCoordinates(record)) {
    return "https://panoramax.xyz/";
  }

  return (
    "https://panoramax.openstreetmap.fr/" +
    `?map=18/${record.lat}/${record.lon}` +
    "&focus=map"
  );
}


function setStatus(text, type = "") {
  const element = document.getElementById(
    "statusBox"
  );

  element.textContent = text;

  element.className =
    `status-box ${type}`.trim();
}


function showViewerMessage(text) {
  const element = document.getElementById(
    "viewerMessage"
  );

  element.textContent = text;

  element.classList.remove(
    "hidden"
  );
}


function hideViewerMessage() {
  document.getElementById(
    "viewerMessage"
  ).classList.add(
    "hidden"
  );
}


/*
 * Die Panoramax-Standardwidgets sind im HTML mit widgets="false"
 * deaktiviert. Dadurch wird insbesondere die PictureLegend samt
 * Metadaten-Bottom-Drawer gar nicht erst erzeugt. Wir brauchen hier
 * deshalb keine DOM-Manipulation oder MutationObserver mehr.
 */
async function ensurePanoramaxReady() {
  if (panoramaReady) {
    return true;
  }

  panoramaViewer = document.getElementById(
    "panoramaxViewer"
  );

  if (!panoramaViewer) {
    throw new Error(
      "Panoramax-Viewer wurde nicht gefunden."
    );
  }

  await customElements.whenDefined(
    "pnx-viewer"
  );

  if (
    typeof panoramaViewer.onceAPIReady ===
    "function"
  ) {
    await panoramaViewer.onceAPIReady();
  }

  panoramaReady = true;

  return true;
}


async function movePanoramaxTo(
  record,
  renderToken
) {
  if (!hasCoordinates(record)) {
    showViewerMessage(
      "Für diesen Eintrag liegt keine " +
      "Georeferenz vor."
    );

    return;
  }

  showViewerMessage(
    "Suche nach einer offenen " +
    "Panoramax-Aufnahme in der Nähe …"
  );

  try {
    await ensurePanoramaxReady();

    if (
      renderToken !==
      latestPanoramaToken
    ) {
      return;
    }

    const lat = Number(record.lat);
    const lon = Number(record.lon);

    if (
      panoramaViewer.map &&
      typeof panoramaViewer.map.flyTo ===
        "function"
    ) {
      panoramaViewer.map.flyTo({
        center: [lon, lat],
        zoom: 18
      });
    }

    if (
      panoramaViewer.psv &&
      typeof panoramaViewer.psv
        .goToPosition === "function"
    ) {
      await panoramaViewer.psv
        .goToPosition(
          lat,
          lon
        );

      if (
        renderToken !==
        latestPanoramaToken
      ) {
        return;
      }

      hideViewerMessage();

      setStatus(
        "Panoramax-Aufnahme in der " +
        "Umgebung gefunden.",
        "ok"
      );

      return;
    }

    throw new Error(
      "Panoramax konnte nicht " +
      "automatisch angesteuert werden."
    );

  } catch (error) {
    if (
      renderToken !==
      latestPanoramaToken
    ) {
      return;
    }

    showViewerMessage(
      "Keine Panoramax-Aufnahme in der " +
      "näheren Umgebung gefunden."
    );

    setStatus(
      error?.message ||
      "Keine Panoramax-Aufnahme gefunden.",
      "warn"
    );
  }
}


async function renderDetail() {
  const record =
    currentGvRecords[
      currentDetailIndex
    ];

  if (!record) {
    return;
  }

  const info =
    gvMetadata[currentGvId] || {};

  const token =
    ++latestPanoramaToken;

  setText(
    "detailGvLabel",
    info.title ||
    "Generalversammlung"
  );

  setText(
    "counter",
    `${currentDetailIndex + 1} / ` +
    `${currentGvRecords.length}`
  );

  setText(
    "name",
    record.name || "Ohne Namen"
  );

  setText(
    "historicAddress",
    String(record.address || "")
      .trim() || "Keine Angabe"
  );

  setText(
    "geocodeAddress",
    record.geocode_query || "–"
  );

  setText(
    "coordinates",
    hasCoordinates(record)
      ? (
          `${Number(record.lat).toFixed(6)}, ` +
          `${Number(record.lon).toFixed(6)}`
        )
      : "Nicht georeferenziert"
  );

  setText(
    "source",
    `${record.document || record.source_file || "–"}` +
    (
      record.page_number
        ? `, S. ${record.page_number}`
        : ""
    )
  );

  setText(
    "actionsO",
    formatNumber(record.actions_o)
  );

  setText(
    "actionsP",
    formatNumber(record.actions_p)
  );

  setText(
    "actionsTotal",
    formatNumber(actionsTotal(record))
  );

  setText(
    "qualityBadge",
    qualityLabel(
      record.geocode_quality
    )
  );

  setText(
    "methodNote",
    record.geocode_note || ""
  );

  const osmLink =
    document.getElementById(
      "osmLink"
    );

  osmLink.href =
    osmUrl(record);

  const panoramaxLink =
    document.getElementById(
      "panoramaxLink"
    );

  panoramaxLink.href =
    panoramaxUrl(record);

  if (!record.address) {
    setStatus(
      "In der historischen Quelle ist " +
      "keine Adresse angegeben.",
      "error"
    );

  } else if (!hasCoordinates(record)) {
    setStatus(
      "Adresse vorhanden, aber keine " +
      "Georeferenz gefunden.",
      "warn"
    );

  } else if (
    record.geocode_quality ===
    "locality"
  ) {
    setStatus(
      "Nur Ortsniveau: Ein Bild in der " +
      "Nähe darf nicht als Wohnhaus " +
      "dieser Person interpretiert werden.",
      "warn"
    );

  } else {
    setStatus(
      "Georeferenz vorhanden; " +
      "Panoramax wird geprüft."
    );
  }

  await movePanoramaxTo(
    record,
    token
  );
}


/* =========================================================
   EVENTS
   ========================================================= */

function installEventListeners() {
  document.getElementById(
    "enterResearchButton"
  ).addEventListener(
    "click",
    enterResearch
  );

  document.getElementById(
    "researchPageButton"
  ).addEventListener(
    "click",
    renderResearch
  );

  document.getElementById(
    "corpusPageButton"
  ).addEventListener(
    "click",
    renderHome
  );

  document.getElementById(
    "nodegoatPageButton"
  ).addEventListener(
    "click",
    renderNodegoat
  );

  document.getElementById(
    "researchToCorpusButton"
  ).addEventListener(
    "click",
    renderHome
  );

  document.getElementById(
    "showGvCorpusButton"
  ).addEventListener(
    "click",
    () => setCorpusMode("gv")
  );

  document.getElementById(
    "showPersonCorpusButton"
  ).addEventListener(
    "click",
    () => setCorpusMode("people")
  );

  document.getElementById(
    "showSharesCorpusButton"
  ).addEventListener(
    "click",
    () => setCorpusMode("shares")
  );

  document.getElementById(
    "sharesEntitySelect"
  ).addEventListener(
    "change",
    renderShareEntityChart
  );

  document.getElementById(
    "personSearch"
  ).addEventListener(
    "input",
    renderPersonCards
  );

  document.getElementById(
    "backPeopleButton"
  ).addEventListener(
    "click",
    () => renderHome("people")
  );

  document.getElementById(
    "backHomeFromPersonButton"
  ).addEventListener(
    "click",
    renderHome
  );

  document.getElementById(
    "backHomeButton"
  ).addEventListener(
    "click",
    renderHome
  );

  document.getElementById(
    "backGvButton"
  ).addEventListener(
    "click",
    renderGv
  );

  document.getElementById(
    "backHomeFromDetailButton"
  ).addEventListener(
    "click",
    renderHome
  );

  document.getElementById(
    "europeButton"
  ).addEventListener(
    "click",
    resetEuropeView
  );

  document.getElementById(
    "shareholderSearch"
  ).addEventListener(
    "input",
    filterShareholderTable
  );

  document.getElementById(
    "prevButton"
  ).addEventListener(
    "click",
    previousDetail
  );

  document.getElementById(
    "nextButton"
  ).addEventListener(
    "click",
    nextDetail
  );

  /*
   * Jahresfelder im Forschungsworkflow.
   * Event Delegation ist robust und funktioniert auch,
   * wenn sich der HTML-Inhalt später verändert.
   */
  document.addEventListener(
    "click",
    event => {
      const button = event.target.closest(
        ".workflow-year-link"
      );

      if (!button) {
        return;
      }

      event.preventDefault();

      const year = Number(
        button.dataset.gvYear
      );

      if (!Number.isInteger(year)) {
        return;
      }

      openWorkflowYear(year);
    }
  );

  document.addEventListener(
    "keydown",
    event => {
      const detailVisible =
        !document.getElementById(
          "detailView"
        ).classList.contains(
          "hidden"
        );

      if (!detailVisible) {
        return;
      }

      if (event.key === "ArrowLeft") {
        previousDetail();
      }

      if (event.key === "ArrowRight") {
        nextDetail();
      }
    }
  );
}


/* =========================================================
   INITIALISIERUNG
   ========================================================= */

async function loadNodegoatSiteData() {
  try {
    const response = await fetch(
      SITE_DATA_URL,
      {
        cache: "no-store"
      }
    );

    if (!response.ok) {
      return false;
    }

    const payload =
      await response.json();

    if (
      !payload ||
      !Array.isArray(payload.records) ||
      !payload.gv_metadata ||
      typeof payload.gv_metadata !== "object"
    ) {
      throw new Error(
        "site-data.json hat nicht die erwartete Struktur."
      );
    }

    allRecords =
      payload.records;

    gvMetadata =
      payload.gv_metadata;

    dataSource = "nodegoat";

    console.info(
      "Forschungsdaten aus nodegoat-Export geladen:",
      payload.meta || {}
    );

    return true;

  } catch (error) {
    console.warn(
      "nodegoat-Export konnte nicht geladen werden:",
      error
    );

    return false;
  }
}


async function loadLegacyData() {
  const [
    dataResponse,
    metadataResponse
  ] = await Promise.all([
    fetch(DATA_URL),
    fetch(GV_METADATA_URL)
  ]);

  if (!dataResponse.ok) {
    throw new Error(
      `geocoded.json: HTTP ${dataResponse.status}`
    );
  }

  if (!metadataResponse.ok) {
    throw new Error(
      `gv-metadata.json: HTTP ${metadataResponse.status}`
    );
  }

  allRecords =
    await dataResponse.json();

  gvMetadata =
    await metadataResponse.json();

  dataSource = "legacy";

  console.warn(
    "site-data.json fehlt. Die Website verwendet vorübergehend " +
    "die alten lokalen JSON-Dateien."
  );
}


async function init() {
  try {
    const nodegoatLoaded =
      await loadNodegoatSiteData();

    if (!nodegoatLoaded) {
      await loadLegacyData();
    }

    gvOrder =
      Object.keys(gvMetadata)
        .filter(
          gvId =>
            recordsForGv(gvId).length > 0
        )
        .sort(
          (a, b) =>
            gvSortValue(a).localeCompare(
              gvSortValue(b)
            )
        );

    buildPersonIndex();

    installEventListeners();

    renderResearch();

  } catch (error) {
    console.error(error);

    document.body.innerHTML = `
      <main class="load-error">
        <h1>
          Die Forschungsdaten konnten nicht geladen werden.
        </h1>

        <p>
          ${escapeHtml(error.message)}
        </p>

        <p>
          Führe zuerst
          <code>py .\\export_nodegoat_for_web.py</code>
          aus. Dadurch wird
          <code>data/site-data.json</code>
          aus nodegoat erzeugt.
        </p>
      </main>
    `;
  }
}

init();
