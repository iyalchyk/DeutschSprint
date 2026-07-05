const state = {
  categories: [],
  manifests: [],
  words: [],
  loadedWordsByVerbId: new Map(),
  currentManifest: null,
  pendingVerbId: "",
  selectedVerbId: "",
  recentVerbIds: [],
  favoriteVerbIds: [],
  visibleVerbIds: [],
  activeVerbIndex: 0
};

const SETTINGS_KEY = "deutschSprint.settings";
const FILE_CACHE_PREFIX = `${SETTINGS_KEY}.file.`;
const FILE_CACHE_TTL_MS = 60 * 60 * 1000;
const DEFAULT_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"];
const DEFAULT_WORD_BASE = "arbeiten";
const MAX_RECENT_VERBS = 6;
const MAX_VERB_RESULTS = 120;

const els = {
  currentVerbName: document.querySelector("#currentVerbName"),
  currentVerbMeta: document.querySelector("#currentVerbMeta"),
  changeVerbButton: document.querySelector("#changeVerbButton"),
  favoriteCurrentVerb: document.querySelector("#favoriteCurrentVerb"),
  verbDialog: document.querySelector("#verbDialog"),
  verbSearch: document.querySelector("#verbSearch"),
  verbResults: document.querySelector("#verbResults"),
  closeVerbDialog: document.querySelector("#closeVerbDialog"),
  overviewText: document.querySelector("#overviewText"),
  translationEn: document.querySelector("#translationEn"),
  translationRu: document.querySelector("#translationRu"),
  levelCheckboxes: [...document.querySelectorAll('input[name="level"]')],
  wordCount: document.querySelector("#wordCount"),
  levelRange: document.querySelector("#levelRange"),
  exportWordsButton: document.querySelector("#exportWordsButton"),
  wordSearch: document.querySelector("#wordSearch"),
  wordTable: document.querySelector(".word-table"),
  wordTableBody: document.querySelector("#wordTableBody")
};

function parseDelimited(text, delimiter) {
  const rows = [];
  let row = [];
  let cell = "";
  let inQuotes = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    const next = text[i + 1];

    if (char === '"' && inQuotes && next === '"') {
      cell += '"';
      i += 1;
    } else if (char === '"') {
      inQuotes = !inQuotes;
    } else if (char === delimiter && !inQuotes) {
      row.push(cell);
      cell = "";
    } else if ((char === "\n" || char === "\r") && !inQuotes) {
      if (char === "\r" && next === "\n") {
        i += 1;
      }
      row.push(cell);
      if (row.some((value) => value.trim() !== "")) {
        rows.push(row);
      }
      row = [];
      cell = "";
    } else {
      cell += char;
    }
  }

  row.push(cell);
  if (row.some((value) => value.trim() !== "")) {
    rows.push(row);
  }

  const headers = rows.shift()?.map((header) => header.replace(/^\uFEFF/, "").trim()) || [];
  return rows.map((values) => Object.fromEntries(headers.map((header, index) => [header, (values[index] || "").trim()])));
}

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

function levelSort(level) {
  const order = { A1: 1, A2: 2, B1: 3, B2: 4, C1: 5, C2: 6 };
  return order[level] || 99;
}

function frequencyRank(word) {
  const rank = Number(word.word_freq);
  return Number.isFinite(rank) ? rank : Number.MAX_SAFE_INTEGER;
}

function selectedTranslations() {
  const languages = [];
  if (els.translationEn.checked) {
    languages.push("en");
  }
  if (els.translationRu.checked) {
    languages.push("ru");
  }
  return languages;
}

function activeLevels() {
  return new Set(els.levelCheckboxes.filter((input) => input.checked).map((input) => input.value));
}

function isLevelActive(level) {
  return !level || activeLevels().has(level);
}

async function loadText(path) {
  const cachedText = readCachedFile(path);
  if (cachedText !== null) {
    return cachedText;
  }

  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${path} konnte nicht geladen werden.`);
  }
  const text = await response.text();
  writeCachedFile(path, text);
  return text;
}

function cacheKeyForPath(path) {
  return `${FILE_CACHE_PREFIX}${path}`;
}

function readCachedFile(path) {
  try {
    const raw = localStorage.getItem(cacheKeyForPath(path));
    if (!raw) {
      return null;
    }

    const cached = JSON.parse(raw);
    const isFresh = Number.isFinite(cached.savedAt) && Date.now() - cached.savedAt <= FILE_CACHE_TTL_MS;
    if (isFresh && typeof cached.text === "string") {
      return cached.text;
    }

    localStorage.removeItem(cacheKeyForPath(path));
  } catch (error) {
    // Fall through to a network load when cached file data is unavailable.
  }
  return null;
}

function writeCachedFile(path, text) {
  try {
    localStorage.setItem(cacheKeyForPath(path), JSON.stringify({
      savedAt: Date.now(),
      text
    }));
  } catch (error) {
    // The app still works if cached file storage is unavailable or full.
  }
}

async function init() {
  try {
    els.overviewText.textContent = "Verfügbare Verben werden geladen ...";
    const manifestData = await fetch("assets/verbs.json").then((response) => {
      if (!response.ok) {
        throw new Error("assets/verbs.json konnte nicht geladen werden.");
      }
      return response.json();
    });

    state.categories = await buildAvailableCategories(manifestData);
    state.manifests = state.categories.flatMap((category) => category.words);
    loadSettings();
    renderVerbChooser();
    bindEvents();

    if (state.manifests.length === 0) {
      renderEmptyState("Keine Wörter im Manifest gefunden.");
      return;
    }

    const settings = readSettings();
    const selectedManifest = selectedManifestFromSettings(settings) || defaultManifest();
    if (selectedManifest) {
      state.selectedVerbId = selectedManifest.id;
      renderVerbChooser();
      await loadVerb(selectedManifest.id);
    } else {
      state.selectedVerbId = "";
      renderVerbChooser();
      renderAwaitingSelection();
    }
  } catch (error) {
    document.body.insertAdjacentHTML("afterbegin", `<div class="error-state">${escapeHtml(error.message)}</div>`);
  }
}

function bindEvents() {
  els.changeVerbButton.addEventListener("click", openVerbDialog);
  els.favoriteCurrentVerb.addEventListener("click", () => toggleFavorite(state.selectedVerbId));
  els.closeVerbDialog.addEventListener("click", closeVerbDialog);
  els.verbDialog.addEventListener("click", (event) => {
    if (event.target === els.verbDialog) {
      closeVerbDialog();
    }
  });
  els.verbSearch.addEventListener("input", () => {
    state.activeVerbIndex = 0;
    renderVerbResults();
  });
  els.verbSearch.addEventListener("keydown", handleVerbSearchKeydown);
  els.verbResults.addEventListener("click", handleVerbResultsClick);
  els.exportWordsButton.addEventListener("click", exportWordsToExcel);
  els.wordSearch.addEventListener("input", renderWords);
  els.translationEn.addEventListener("change", handleSettingsChange);
  els.translationRu.addEventListener("change", handleSettingsChange);
  els.levelCheckboxes.forEach((input) => input.addEventListener("change", handleSettingsChange));
}

function normalizeCategories(data) {
  if (Array.isArray(data)) {
  return [{
    key: "verbs",
    label: "Verben",
    labelEn: "",
    labelRu: "",
    words: data
  }];
  }

  return Object.entries(data || {}).map(([key, category]) => ({
    key,
    label: category.category_name_de || category.category_name_en || key,
    labelEn: category.category_name_en || "",
    labelRu: category.category_name_ru || "",
    words: Array.isArray(category.words) ? category.words : []
  }));
}

async function buildAvailableCategories(data) {
  const categories = normalizeCategories(data);
  return categories
    .map((category) => {
      const words = category.words
        .filter((word) => word.enriched)
        .map((word) => ({
          ...word,
          id: `${category.key}:${word.base}:${word.enriched}`,
          categoryKey: category.key,
          categoryLabel: category.label,
          categoryLabelEn: category.labelEn,
          categoryLabelRu: category.labelRu,
          wordCount: null,
          levelCounts: null
        }))
        .sort((a, b) => (a.label || a.base).localeCompare(b.label || b.base, "de"));

      return {
        ...category,
        words
      };
    })
    .filter((category) => category.words.length > 0)
    .sort((a, b) => a.label.localeCompare(b.label, "de"));
}

function countWordsByLevel(words) {
  return words.reduce((counts, word) => {
    const level = word.word_level || "";
    counts[level] = (counts[level] || 0) + 1;
    return counts;
  }, {});
}

function selectedManifestFromSettings(settings) {
  return state.manifests.find((item) => item.id === settings.selectedVerbId);
}

function defaultManifest() {
  return state.manifests.find((item) => item.base === DEFAULT_WORD_BASE);
}

function currentManifest() {
  return state.manifests.find((item) => item.id === state.selectedVerbId) || state.currentManifest;
}

function renderVerbChooser() {
  if (state.categories.length === 0) {
    els.currentVerbName.textContent = "-";
    els.currentVerbMeta.textContent = "Keine Verben verfügbar";
    els.changeVerbButton.disabled = true;
    els.favoriteCurrentVerb.disabled = true;
    return;
  }

  const hasCurrentManifest = Boolean(currentManifest());
  els.changeVerbButton.disabled = false;
  els.favoriteCurrentVerb.disabled = !hasCurrentManifest;
  renderCurrentVerb();
  if (els.verbDialog.open) {
    renderVerbResults();
  }
}

function renderCurrentVerb() {
  const manifest = currentManifest();
  if (!manifest) {
    els.currentVerbName.textContent = "Verb auswählen";
    els.currentVerbMeta.textContent = `${state.manifests.length} Verben verfügbar`;
    els.changeVerbButton.textContent = "Verb auswählen";
    els.favoriteCurrentVerb.textContent = "☆";
    els.favoriteCurrentVerb.setAttribute("aria-pressed", "false");
    els.favoriteCurrentVerb.setAttribute("aria-label", "Aktuelles Verb merken");
    return;
  }

  els.changeVerbButton.textContent = "Verb wechseln";
  els.currentVerbName.textContent = manifest.label || manifest.base;
  els.currentVerbMeta.textContent = currentVerbMeta(manifest);
  els.favoriteCurrentVerb.textContent = isFavorite(manifest.id) ? "★" : "☆";
  els.favoriteCurrentVerb.setAttribute("aria-pressed", String(isFavorite(manifest.id)));
  els.favoriteCurrentVerb.setAttribute("aria-label", `${isFavorite(manifest.id) ? "Merkliste entfernen:" : "Merken:"} ${manifest.label || manifest.base}`);
}

function openVerbDialog() {
  if (state.manifests.length === 0) {
    return;
  }

  els.verbSearch.value = "";
  state.activeVerbIndex = 0;
  renderVerbResults();
  const selectedIndex = state.visibleVerbIds.indexOf(state.selectedVerbId);
  if (selectedIndex >= 0) {
    state.activeVerbIndex = selectedIndex;
    updateActiveVerbOption();
  }
  els.verbDialog.showModal();
  requestAnimationFrame(() => els.verbSearch.focus());
}

function closeVerbDialog() {
  els.verbDialog.close();
  els.changeVerbButton.focus();
}

function handleVerbSearchKeydown(event) {
  if (event.key === "ArrowDown") {
    event.preventDefault();
    moveActiveVerb(1);
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    moveActiveVerb(-1);
  } else if (event.key === "Enter") {
    event.preventDefault();
    const id = state.visibleVerbIds[state.activeVerbIndex] || state.visibleVerbIds[0];
    if (id) {
      selectVerb(id);
    }
  } else if (event.key === "Escape") {
    closeVerbDialog();
  }
}

function handleVerbResultsClick(event) {
  const favoriteButton = event.target.closest("[data-favorite-id]");
  if (favoriteButton) {
    toggleFavorite(favoriteButton.dataset.favoriteId);
    return;
  }

  const result = event.target.closest("[data-verb-id]");
  if (result) {
    selectVerb(result.dataset.verbId);
  }
}

function moveActiveVerb(direction) {
  if (state.visibleVerbIds.length === 0) {
    return;
  }

  state.activeVerbIndex = (state.activeVerbIndex + direction + state.visibleVerbIds.length) % state.visibleVerbIds.length;
  updateActiveVerbOption();
}

function updateActiveVerbOption() {
  const activeId = state.visibleVerbIds[state.activeVerbIndex];
  els.verbResults.querySelectorAll("[data-verb-id]").forEach((item) => {
    const isActive = item.dataset.verbId === activeId;
    item.classList.toggle("is-active", isActive);
    item.setAttribute("aria-selected", String(isActive));
    if (isActive) {
      item.scrollIntoView({ block: "nearest" });
    }
  });
}

function selectVerb(id) {
  closeVerbDialog();
  loadVerb(id);
}

function renderVerbResults() {
  const query = els.verbSearch.value.trim();
  const groups = query ? searchedVerbGroups(query) : defaultVerbGroups();
  const visibleIds = [];
  const html = groups
    .filter((group) => group.items.length > 0)
    .map((group) => {
      const items = group.items.map((item) => {
        visibleIds.push(item.id);
        return renderVerbResult(item, query);
      }).join("");
      return `
        <section class="verb-result-section" aria-label="${escapeHtml(group.label)}">
          <h3>${escapeHtml(group.label)}</h3>
          <div class="verb-result-list">${items}</div>
        </section>
      `;
    })
    .join("");

  state.visibleVerbIds = visibleIds;
  if (state.activeVerbIndex >= visibleIds.length) {
    state.activeVerbIndex = 0;
  }

  els.verbResults.innerHTML = html || '<p class="empty-cell">Keine passenden Verben.</p>';
  updateActiveVerbOption();
}

function defaultVerbGroups() {
  const recent = idsToManifests(state.recentVerbIds);
  const favorites = idsToManifests(state.favoriteVerbIds);
  const recentAndFavoriteIds = new Set([...recent, ...favorites].map((item) => item.id));
  const all = sortedCategoriesForActiveLevels()
    .flatMap((category) => category.words)
    .filter((item) => !recentAndFavoriteIds.has(item.id));

  return [
    { label: "Zuletzt verwendet", items: recent },
    { label: "Merkliste", items: favorites },
    { label: "Alle Verben", items: all }
  ];
}

function searchedVerbGroups(query) {
  return [{
    label: "Suchergebnisse",
    items: state.manifests
      .map((item) => ({ item, score: verbSearchScore(item, query) }))
      .filter((result) => result.score > 0)
      .sort((a, b) => b.score - a.score || activeWordCount(b.item) - activeWordCount(a.item) || verbLabel(a.item).localeCompare(verbLabel(b.item), "de"))
      .slice(0, MAX_VERB_RESULTS)
      .map((result) => result.item)
  }];
}

function renderVerbResult(item, query) {
  const selected = item.id === state.selectedVerbId;
  const favorite = isFavorite(item.id);
  const meta = verbResultMeta(item);
  return `
    <div class="verb-result ${selected ? "is-selected" : ""}" role="option" aria-selected="false" data-verb-id="${escapeHtml(item.id)}">
      <button class="verb-result-main" type="button">
        <span class="verb-result-name">${highlightMatch(verbLabel(item), query)}</span>
        <span class="verb-result-meta">${escapeHtml(meta)}</span>
      </button>
      <button class="favorite-toggle ${favorite ? "is-favorite" : ""}" type="button" data-favorite-id="${escapeHtml(item.id)}" aria-pressed="${favorite}" aria-label="${favorite ? "Aus Merkliste entfernen:" : "Merken:"} ${escapeHtml(verbLabel(item))}" title="${favorite ? "Aus Merkliste entfernen" : "Merken"}">${favorite ? "★" : "☆"}</button>
    </div>
  `;
}

function idsToManifests(ids) {
  return ids
    .map((id) => state.manifests.find((item) => item.id === id))
    .filter(Boolean);
}

function addRecentVerb(id) {
  if (!id) {
    return;
  }

  state.recentVerbIds = [id, ...state.recentVerbIds.filter((item) => item !== id)].slice(0, MAX_RECENT_VERBS);
}

function toggleFavorite(id) {
  if (!id) {
    return;
  }

  if (isFavorite(id)) {
    state.favoriteVerbIds = state.favoriteVerbIds.filter((item) => item !== id);
  } else {
    state.favoriteVerbIds = [id, ...state.favoriteVerbIds];
  }

  saveSettings();
  renderVerbChooser();
}

function isFavorite(id) {
  return state.favoriteVerbIds.includes(id);
}

function verbLabel(item) {
  return item.label || item.base || "";
}

function verbSearchScore(item, query) {
  const normalizedQuery = normalizeSearch(query);
  if (!normalizedQuery) {
    return 1;
  }

  const label = normalizeSearch(verbLabel(item));
  const base = normalizeSearch(item.base);
  const category = normalizeSearch([item.categoryLabel, item.categoryLabelEn, item.categoryLabelRu].join(" "));
  const verbHaystack = `${label} ${base}`;

  if (label === normalizedQuery || base === normalizedQuery) {
    return 100;
  }
  if (label.startsWith(normalizedQuery) || base.startsWith(normalizedQuery)) {
    return 85;
  }
  if (label.includes(normalizedQuery) || base.includes(normalizedQuery)) {
    return 70;
  }
  if (category.includes(normalizedQuery)) {
    return 50;
  }
  if (fuzzyIncludes(verbHaystack, normalizedQuery)) {
    return 30;
  }
  return 0;
}

function normalizeSearch(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/ß/g, "ss")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9а-яё]+/gi, " ")
    .trim();
}

function fuzzyIncludes(value, query) {
  let valueIndex = 0;
  for (const char of query.replace(/\s+/g, "")) {
    valueIndex = value.indexOf(char, valueIndex);
    if (valueIndex === -1) {
      return false;
    }
    valueIndex += 1;
  }
  return true;
}

function highlightMatch(value, query) {
  const escaped = escapeHtml(value);
  const normalizedQuery = query.trim();
  if (!normalizedQuery) {
    return escaped;
  }

  const words = normalizedQuery
    .split(/\s+/)
    .map(escapeRegExp)
    .filter(Boolean);
  if (words.length === 0) {
    return escaped;
  }

  return escaped.replace(new RegExp(`(${words.join("|")})`, "gi"), "<mark>$1</mark>");
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function sortedCategoriesForActiveLevels() {
  return [...state.categories].sort((a, b) => a.label.localeCompare(b.label, "de"));
}

function activeWordCount(word) {
  const levels = activeLevels();
  return Object.entries(word.levelCounts || {}).reduce((total, [level, count]) => {
    return !level || levels.has(level) ? total + count : total;
  }, 0);
}

function hasWordStats(word) {
  return word.wordCount !== null && word.levelCounts !== null;
}

function currentVerbMeta(manifest) {
  const count = hasWordStats(manifest) ? `${activeWordCount(manifest)} Wörter` : "";
  const loading = state.pendingVerbId === manifest.id ? "Lädt" : "";
  return [loading || count, manifest.categoryLabel].filter(Boolean).join(" · ");
}

function verbResultMeta(manifest) {
  const count = hasWordStats(manifest) ? `${activeWordCount(manifest)} Wörter` : "";
  return [manifest.categoryLabel, count].filter(Boolean).join(" · ");
}

async function loadVerb(id) {
  const manifest = state.manifests.find((item) => item.id === id);
  if (!manifest) {
    return;
  }

  state.selectedVerbId = id;
  state.currentManifest = manifest;
  state.pendingVerbId = id;
  addRecentVerb(id);
  saveSettings();
  renderVerbChooser();
  renderLoadingState();

  try {
    const words = state.loadedWordsByVerbId.get(id) || parseVerbWords(await loadText(manifest.enriched));
    state.loadedWordsByVerbId.set(id, words);

    if (state.selectedVerbId !== id) {
      return;
    }

    manifest.wordCount = words.length;
    manifest.levelCounts = countWordsByLevel(words);
    state.words = words;
    state.pendingVerbId = "";
    renderVerbChooser();
    renderOverview();
    renderWords();
  } catch (error) {
    if (state.selectedVerbId !== id) {
      return;
    }
    state.pendingVerbId = "";
    renderVerbChooser();
    renderEmptyState(`Die Datei für „${verbLabel(manifest)}“ konnte nicht geladen werden.`);
  }
}

function parseVerbWords(text) {
  return parseDelimited(text, "|").sort((a, b) => {
    const levelDiff = levelSort(a.word_level) - levelSort(b.word_level);
    if (levelDiff) {
      return levelDiff;
    }
    const rankDiff = frequencyRank(a) - frequencyRank(b);
    return rankDiff || a.word.localeCompare(b.word, "de");
  });
}

function renderOverview() {
  updateStats();
  const label = state.currentManifest?.label || state.currentManifest?.base || "dieses Set";
  const category = state.currentManifest?.categoryLabel;
  els.overviewText.textContent = category
    ? `Das Set „${label}“ gehört zur Kategorie „${category}“ und zeigt das Grundverb, abgeleitete Formen und Nomen aus derselben Wortfamilie.`
    : `Das Set „${label}“ zeigt das Grundverb, abgeleitete Formen und Nomen aus derselben Wortfamilie.`;
}

function renderWords() {
  if (state.pendingVerbId === state.selectedVerbId && state.words.length === 0) {
    renderLoadingState();
    return;
  }

  const languages = selectedTranslations();
  els.wordTable.classList.toggle("no-translations", languages.length === 0);
  const visibleWords = filteredWords(languages);
  els.exportWordsButton.disabled = visibleWords.length === 0;

  if (visibleWords.length === 0) {
    const colspan = languages.length > 0 ? 8 : 7;
    els.wordTableBody.innerHTML = `<tr><td colspan="${colspan}" class="empty-cell">Keine Treffer.</td></tr>`;
    return;
  }

  els.wordTableBody.innerHTML = visibleWords.map((word) => `
    <tr class="${isLevelActive(word.word_level) ? "" : "inactive-row"}">
      <th scope="row">${escapeHtml(word.word)}</th>
      <td data-label="Niveau"><span class="level">${escapeHtml(word.word_level || "-")}</span></td>
      ${languages.length > 0 ? `<td class="translation-column" data-label="Übersetzung">${renderTranslationLines(word, "word")}</td>` : ""}
      <td data-label="Synonyme">${escapeHtml(word.word_synonyms || "-")}</td>
      <td data-label="Beispiel">${renderExampleLines(word)}</td>
      <td data-label="Satzparaphrase">${escapeHtml(word.sentence_synonym || "-")}</td>
      <td data-label="Kollokationen">${renderListLines(word.typical_collocations)}</td>
      <td data-label="Verwendung">${renderUsageComments(word)}</td>
    </tr>
  `).join("");
}

function filteredWords(languages = selectedTranslations()) {
  const query = els.wordSearch.value.trim().toLowerCase();
  return state.words.filter((word) => {
    const haystack = [
      word.word,
      word.word_synonyms,
      word.sentence_example,
      word.sentence_synonym,
      word.typical_collocations,
      word.usage_comments_en,
      ...languages.map((language) => language === "en" ? word.word_translation_en : word.word_translation_ru),
      ...languages.map((language) => language === "en" ? word.sentence_example_translation_en : word.sentence_example_translation_ru)
    ].join(" ").toLowerCase();
    return haystack.includes(query);
  });
}

function exportWordsToExcel() {
  const languages = selectedTranslations();
  const words = filteredWords(languages);
  if (words.length === 0) {
    return;
  }

  const columns = exportColumns(languages);
  const title = state.currentManifest?.label || state.currentManifest?.base || "Wortschatz";
  const blob = createXlsxBlob(columns, words);
  const link = document.createElement("a");
  const url = URL.createObjectURL(blob);
  link.href = url;
  link.download = `${fileSlug(title)}-wortschatz.xlsx`;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function exportColumns(languages) {
  const columns = [
    { label: "Wort", value: (word) => word.word },
    { label: "Niveau", value: (word) => word.word_level },
    { label: "Synonyme", value: (word) => word.word_synonyms },
    { label: "Beispiel", value: (word) => exampleTextForExport(word, languages) },
    { label: "Satzparaphrase", value: (word) => word.sentence_synonym },
    { label: "Kollokationen", value: (word) => splitListForExport(word.typical_collocations) },
    { label: "Verwendung", value: (word) => word.usage_comments_en }
  ];

  if (languages.length > 0) {
    columns.splice(2, 0, { label: "Übersetzung", value: (word) => wordTranslationsForExport(word, languages) });
  }

  return columns;
}

function wordTranslationsForExport(word, languages) {
  return languages.map((language) => {
    return language === "en" ? word.word_translation_en : word.word_translation_ru;
  }).filter(Boolean).join("\n");
}

function exampleTextForExport(word, languages) {
  const translations = languages.map((language) => {
    return language === "en" ? word.sentence_example_translation_en : word.sentence_example_translation_ru;
  }).filter(Boolean);
  return [word.sentence_example, ...translations].filter(Boolean).join("\n");
}

function splitListForExport(value) {
  return String(value || "")
    .split(";")
    .map((item) => item.trim())
    .filter(Boolean)
    .join("\n");
}

function createXlsxBlob(columns, words) {
  const worksheet = createWorksheetXml(columns, words);
  const files = {
    "[Content_Types].xml": `<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>`,
    "_rels/.rels": `<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>`,
    "xl/workbook.xml": `<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Wortschatz" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>`,
    "xl/_rels/workbook.xml.rels": `<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>`,
    "xl/worksheets/sheet1.xml": worksheet
  };
  return createZipBlob(files, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
}

function createWorksheetXml(columns, words) {
  const headerRow = createWorksheetRow(columns.map((column) => column.label), 1);
  const bodyRows = words.map((word, index) => {
    return createWorksheetRow(columns.map((column) => column.value(word)), index + 2);
  }).join("");
  const columnDefinitions = columns.map((_, index) => {
    const column = index + 1;
    return `<col min="${column}" max="${column}" width="${index < 2 ? 14 : 34}" customWidth="1"/>`;
  }).join("");

  return `<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <cols>${columnDefinitions}</cols>
  <sheetData>${headerRow}${bodyRows}</sheetData>
</worksheet>`;
}

function createWorksheetRow(values, rowNumber) {
  const cells = values.map((value, index) => {
    const ref = `${spreadsheetColumnName(index + 1)}${rowNumber}`;
    return `<c r="${ref}" t="inlineStr"><is><t xml:space="preserve">${escapeXml(value || "-")}</t></is></c>`;
  }).join("");
  return `<row r="${rowNumber}">${cells}</row>`;
}

function spreadsheetColumnName(index) {
  let name = "";
  let value = index;
  while (value > 0) {
    value -= 1;
    name = String.fromCharCode(65 + (value % 26)) + name;
    value = Math.floor(value / 26);
  }
  return name;
}

function createZipBlob(files, type) {
  const encoder = new TextEncoder();
  const localParts = [];
  const centralParts = [];
  let offset = 0;

  Object.entries(files).forEach(([name, content]) => {
    const nameBytes = encoder.encode(name);
    const data = encoder.encode(content);
    const crc = crc32(data);
    const localHeader = concatBytes(
      uint32(0x04034b50),
      uint16(20),
      uint16(0),
      uint16(0),
      uint16(0),
      uint16(0),
      uint32(crc),
      uint32(data.length),
      uint32(data.length),
      uint16(nameBytes.length),
      uint16(0)
    );
    const centralHeader = concatBytes(
      uint32(0x02014b50),
      uint16(20),
      uint16(20),
      uint16(0),
      uint16(0),
      uint16(0),
      uint16(0),
      uint32(crc),
      uint32(data.length),
      uint32(data.length),
      uint16(nameBytes.length),
      uint16(0),
      uint16(0),
      uint16(0),
      uint16(0),
      uint32(0),
      uint32(offset)
    );

    localParts.push(localHeader, nameBytes, data);
    centralParts.push(centralHeader, nameBytes);
    offset += localHeader.length + nameBytes.length + data.length;
  });

  const centralDirectoryOffset = offset;
  const centralDirectorySize = centralParts.reduce((total, part) => total + part.length, 0);
  const endRecord = concatBytes(
    uint32(0x06054b50),
    uint16(0),
    uint16(0),
    uint16(Object.keys(files).length),
    uint16(Object.keys(files).length),
    uint32(centralDirectorySize),
    uint32(centralDirectoryOffset),
    uint16(0)
  );

  return new Blob([...localParts, ...centralParts, endRecord], { type });
}

function crc32(bytes) {
  let crc = -1;
  for (const byte of bytes) {
    crc = (crc >>> 8) ^ CRC_TABLE[(crc ^ byte) & 0xff];
  }
  return (crc ^ -1) >>> 0;
}

const CRC_TABLE = Array.from({ length: 256 }, (_, index) => {
  let value = index;
  for (let bit = 0; bit < 8; bit += 1) {
    value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
  }
  return value >>> 0;
});

function uint16(value) {
  return new Uint8Array([value & 0xff, (value >>> 8) & 0xff]);
}

function uint32(value) {
  return new Uint8Array([
    value & 0xff,
    (value >>> 8) & 0xff,
    (value >>> 16) & 0xff,
    (value >>> 24) & 0xff
  ]);
}

function concatBytes(...parts) {
  const length = parts.reduce((total, part) => total + part.length, 0);
  const bytes = new Uint8Array(length);
  let offset = 0;
  parts.forEach((part) => {
    bytes.set(part, offset);
    offset += part.length;
  });
  return bytes;
}

function escapeXml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function fileSlug(value) {
  const slug = String(value || "wortschatz")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/ß/g, "ss")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug || "wortschatz";
}

function handleSettingsChange() {
  saveSettings();
  renderVerbChooser();
  if (!currentManifest() && !state.pendingVerbId) {
    renderAwaitingSelection();
    return;
  }

  renderWords();
  updateStats();
}

function loadSettings() {
  const settings = readSettings();
  state.selectedVerbId = settings.selectedVerbId;
  state.recentVerbIds = settings.recentVerbIds;
  state.favoriteVerbIds = settings.favoriteVerbIds;
  els.translationEn.checked = settings.translations.includes("en");
  els.translationRu.checked = settings.translations.includes("ru");
  els.levelCheckboxes.forEach((input) => {
    input.checked = settings.levels.includes(input.value);
  });
}

function readSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) {
      return defaultSettings();
    }
    const parsed = JSON.parse(raw);
    return {
      translations: Array.isArray(parsed.translations) ? parsed.translations : ["en", "ru"],
      levels: Array.isArray(parsed.levels) ? parsed.levels : DEFAULT_LEVELS,
      selectedVerbId: typeof parsed.selectedVerbId === "string" ? parsed.selectedVerbId : "",
      recentVerbIds: Array.isArray(parsed.recentVerbIds) ? parsed.recentVerbIds.filter((id) => typeof id === "string") : [],
      favoriteVerbIds: Array.isArray(parsed.favoriteVerbIds) ? parsed.favoriteVerbIds.filter((id) => typeof id === "string") : []
    };
  } catch (error) {
    return defaultSettings();
  }
}

function saveSettings() {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify({
      translations: selectedTranslations(),
      levels: [...activeLevels()],
      selectedVerbId: state.selectedVerbId,
      recentVerbIds: state.recentVerbIds,
      favoriteVerbIds: state.favoriteVerbIds
    }));
  } catch (error) {
    // The app still works if storage is unavailable.
  }
}

function defaultSettings() {
  return {
    translations: ["en", "ru"],
    levels: DEFAULT_LEVELS,
    selectedVerbId: "",
    recentVerbIds: [],
    favoriteVerbIds: []
  };
}

function activeWords() {
  return state.words.filter((word) => isLevelActive(word.word_level));
}

function updateStats() {
  const words = activeWords();
  const levels = unique(words.map((word) => word.word_level)).sort((a, b) => levelSort(a) - levelSort(b));
  els.wordCount.textContent = words.length;
  els.levelRange.textContent = levels.length > 1 ? `${levels[0]}-${levels[levels.length - 1]}` : levels[0] || "-";
}

function renderAwaitingSelection() {
  state.words = [];
  updateStats();
  els.exportWordsButton.disabled = true;
  els.overviewText.textContent = "Wähle ein Verb, um die Wortfamilie zu laden.";
  const colspan = selectedTranslations().length > 0 ? 8 : 7;
  els.wordTableBody.innerHTML = `<tr><td colspan="${colspan}" class="empty-cell">Wähle ein Verb aus.</td></tr>`;
}

function renderLoadingState() {
  state.words = [];
  updateStats();
  els.exportWordsButton.disabled = true;
  els.overviewText.textContent = "Daten werden geladen ...";
  const colspan = selectedTranslations().length > 0 ? 8 : 7;
  els.wordTableBody.innerHTML = `<tr><td colspan="${colspan}" class="empty-cell">Daten werden geladen ...</td></tr>`;
}

function renderEmptyState(message) {
  state.words = [];
  updateStats();
  els.exportWordsButton.disabled = true;
  els.overviewText.textContent = message;
  els.wordTableBody.innerHTML = '<tr><td colspan="8" class="empty-cell">Keine Daten verfügbar.</td></tr>';
}

function renderTranslationLines(item, kind) {
  return selectedTranslations().map((language, index) => {
    const value = language === "en"
      ? item[`${kind}_translation_en`]
      : item[`${kind}_translation_ru`];
    const text = escapeHtml(value || "");
    return index === 0 ? text : `<span>${text}</span>`;
  }).join("<br>");
}

function renderExampleLines(word) {
  const translations = selectedTranslations().map((language) => {
    const value = language === "en"
      ? word.sentence_example_translation_en
      : word.sentence_example_translation_ru;
    return `<span>${escapeHtml(value || "")}</span>`;
  });
  return [escapeHtml(word.sentence_example), ...translations].join("<br>");
}

function renderListLines(value) {
  const items = String(value || "")
    .split(";")
    .map((item) => item.trim())
    .filter(Boolean);

  if (items.length === 0) {
    return "-";
  }

  return items.map((item) => escapeHtml(item)).join("<br>");
}

function renderUsageComments(word) {
  return escapeHtml(word.usage_comments_en || "-");
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

init();
