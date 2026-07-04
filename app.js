const state = {
  categories: [],
  manifests: [],
  words: [],
  currentManifest: null
};

const SETTINGS_KEY = "deutschSprint.settings";
const DEFAULT_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"];
const DEFAULT_WORD_BASE = "arbeiten";

const els = {
  verbSelect: document.querySelector("#verbSelect"),
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
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${path} konnte nicht geladen werden.`);
  }
  return response.text();
}

async function init() {
  try {
    els.overviewText.textContent = "Verfügbare Dateien werden geprüft ...";
    const manifestData = await fetch("assets/verbs.json").then((response) => {
      if (!response.ok) {
        throw new Error("assets/verbs.json konnte nicht geladen werden.");
      }
      return response.json();
    });

    state.categories = await buildAvailableCategories(manifestData);
    state.manifests = state.categories.flatMap((category) => category.words);
    loadSettings();
    renderVerbSelect();
    bindEvents();

    if (state.manifests.length === 0) {
      renderEmptyState("Keine Wörter mit vorhandener Enriched-Datei gefunden.");
      return;
    }

    const settings = readSettings();
    const selectedManifest = selectedManifestFromSettings(settings) || defaultManifest() || state.manifests[0];
    els.verbSelect.value = selectedManifest.id;
    await loadVerb(selectedManifest.id);
  } catch (error) {
    document.body.insertAdjacentHTML("afterbegin", `<div class="error-state">${escapeHtml(error.message)}</div>`);
  }
}

function bindEvents() {
  els.verbSelect.addEventListener("change", () => {
    saveSettings();
    loadVerb(els.verbSelect.value);
  });
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
      words: data
    }];
  }

  return Object.entries(data || {}).map(([key, category]) => ({
    key,
    label: category.category_name_de || category.category_name_en || key,
    words: Array.isArray(category.words) ? category.words : []
  }));
}

async function buildAvailableCategories(data) {
  const categories = normalizeCategories(data);
  const availableCategories = [];

  for (const category of categories) {
    const checks = await Promise.all(category.words.map(async (word) => {
      const wordStats = await enrichedWordStats(word.enriched);
      if (!wordStats) {
        return null;
      }

      const manifest = {
        ...word,
        id: `${category.key}:${word.base}:${word.enriched}`,
        categoryKey: category.key,
        categoryLabel: category.label,
        wordCount: wordStats.total,
        levelCounts: wordStats.levelCounts
      };
      return manifest;
    }));
    const words = checks
      .filter(Boolean)
      .sort((a, b) => (a.label || a.base).localeCompare(b.label || b.base, "de"));

    if (words.length > 0) {
      availableCategories.push({
        ...category,
        totalWordCount: words.reduce((total, word) => total + word.wordCount, 0),
        words
      });
    }
  }

  return availableCategories.sort((a, b) => {
    const countDiff = b.totalWordCount - a.totalWordCount;
    return countDiff || a.label.localeCompare(b.label, "de");
  });
}

async function enrichedWordStats(path) {
  if (!path) {
    return null;
  }

  try {
    const response = await fetch(path, { method: "HEAD", cache: "no-store" });
    if (!response.ok && ![405, 501].includes(response.status)) {
      return null;
    }
  } catch (error) {
    // Fall back below for static servers or local setups that do not support HEAD.
  }

  try {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) {
      return null;
    }
    const words = parseDelimited(await response.text(), "|");
    return {
      total: words.length,
      levelCounts: countWordsByLevel(words)
    };
  } catch (error) {
    return null;
  }
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

function renderVerbSelect() {
  const selectedId = els.verbSelect.value;

  if (state.categories.length === 0) {
    els.verbSelect.innerHTML = '<option value="">Keine verfügbaren Wörter</option>';
    els.verbSelect.disabled = true;
    return;
  }

  els.verbSelect.disabled = false;
  els.verbSelect.innerHTML = sortedCategoriesForActiveLevels().map((category) => `
    <optgroup label="${escapeHtml(category.label)}">
      ${category.words.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(`${item.label || item.base} (${activeWordCount(item)})`)}</option>`).join("")}
    </optgroup>
  `).join("");

  if (state.manifests.some((item) => item.id === selectedId)) {
    els.verbSelect.value = selectedId;
  }
}

function sortedCategoriesForActiveLevels() {
  return [...state.categories].sort((a, b) => {
    const countDiff = activeCategoryWordCount(b) - activeCategoryWordCount(a);
    return countDiff || a.label.localeCompare(b.label, "de");
  });
}

function activeCategoryWordCount(category) {
  return category.words.reduce((total, word) => total + activeWordCount(word), 0);
}

function activeWordCount(word) {
  const levels = activeLevels();
  return Object.entries(word.levelCounts || {}).reduce((total, [level, count]) => {
    return !level || levels.has(level) ? total + count : total;
  }, 0);
}

async function loadVerb(id) {
  const manifest = state.manifests.find((item) => item.id === id);
  if (!manifest) {
    return;
  }

  state.currentManifest = manifest;
  els.overviewText.textContent = "Daten werden geladen ...";
  const wordText = await loadText(manifest.enriched);

  state.words = parseDelimited(wordText, "|").sort((a, b) => {
    const levelDiff = levelSort(a.word_level) - levelSort(b.word_level);
    if (levelDiff) {
      return levelDiff;
    }
    const rankDiff = frequencyRank(a) - frequencyRank(b);
    return rankDiff || a.word.localeCompare(b.word, "de");
  });

  renderOverview();
  renderWords();
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
  renderVerbSelect();
  renderWords();
  updateStats();
}

function loadSettings() {
  const settings = readSettings();
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
      return { translations: ["en", "ru"], levels: DEFAULT_LEVELS, selectedVerbId: "" };
    }
    const parsed = JSON.parse(raw);
    return {
      translations: Array.isArray(parsed.translations) ? parsed.translations : ["en", "ru"],
      levels: Array.isArray(parsed.levels) ? parsed.levels : DEFAULT_LEVELS,
      selectedVerbId: typeof parsed.selectedVerbId === "string" ? parsed.selectedVerbId : ""
    };
  } catch (error) {
    return { translations: ["en", "ru"], levels: DEFAULT_LEVELS, selectedVerbId: "" };
  }
}

function saveSettings() {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify({
      translations: selectedTranslations(),
      levels: [...activeLevels()],
      selectedVerbId: els.verbSelect.value
    }));
  } catch (error) {
    // The app still works if storage is unavailable.
  }
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
