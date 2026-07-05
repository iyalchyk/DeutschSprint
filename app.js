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

  const query = els.wordSearch.value.trim().toLowerCase();
  const languages = selectedTranslations();
  els.wordTable.classList.toggle("no-translations", languages.length === 0);

  const visibleWords = state.words.filter((word) => {
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
  els.overviewText.textContent = "Wähle ein Verb, um die Wortfamilie zu laden.";
  const colspan = selectedTranslations().length > 0 ? 8 : 7;
  els.wordTableBody.innerHTML = `<tr><td colspan="${colspan}" class="empty-cell">Wähle ein Verb aus.</td></tr>`;
}

function renderLoadingState() {
  state.words = [];
  updateStats();
  els.overviewText.textContent = "Daten werden geladen ...";
  const colspan = selectedTranslations().length > 0 ? 8 : 7;
  els.wordTableBody.innerHTML = `<tr><td colspan="${colspan}" class="empty-cell">Daten werden geladen ...</td></tr>`;
}

function renderEmptyState(message) {
  state.words = [];
  updateStats();
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
