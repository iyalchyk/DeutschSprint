const state = {
  manifests: [],
  words: [],
  exercises: [],
  filteredExercises: [],
  currentIndex: 0,
  correctCount: 0,
  selectedAnswer: "",
  sentenceParts: [],
  answeredIds: new Set()
};

const SETTINGS_KEY = "deutschSprint.settings";
const DEFAULT_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"];

const els = {
  verbSelect: document.querySelector("#verbSelect"),
  overviewText: document.querySelector("#overviewText"),
  translationEn: document.querySelector("#translationEn"),
  translationRu: document.querySelector("#translationRu"),
  levelCheckboxes: [...document.querySelectorAll('input[name="level"]')],
  wordCount: document.querySelector("#wordCount"),
  exerciseCount: document.querySelector("#exerciseCount"),
  levelRange: document.querySelector("#levelRange"),
  wordSearch: document.querySelector("#wordSearch"),
  wordTable: document.querySelector(".word-table"),
  wordTableBody: document.querySelector("#wordTableBody"),
  typeFilter: document.querySelector("#typeFilter"),
  progressText: document.querySelector("#progressText"),
  progressBar: document.querySelector("#progressBar"),
  scoreText: document.querySelector("#scoreText"),
  exerciseType: document.querySelector("#exerciseType"),
  exerciseWord: document.querySelector("#exerciseWord"),
  questionText: document.querySelector("#questionText"),
  answerArea: document.querySelector("#answerArea"),
  feedback: document.querySelector("#feedback"),
  checkButton: document.querySelector("#checkButton"),
  nextButton: document.querySelector("#nextButton"),
  exampleDe: document.querySelector("#exampleDe"),
  exampleRu: document.querySelector("#exampleRu"),
  exampleEn: document.querySelector("#exampleEn")
};

const typeLabels = {
  multiple_choice_de_en: "DE -> EN",
  multiple_choice_ru_de: "RU -> DE",
  multiple_choice_synonym: "Synonym",
  sentence_translation_de_en: "Übersetzung EN",
  sentence_translation_de_ru: "Übersetzung RU",
  sentence_order: "Wortstellung",
  multiple_choice_sentence_paraphrase: "Paraphrase",
  word_family_base: "Wortfamilie"
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

  const headers = rows.shift().map((header) => header.replace(/^\uFEFF/, "").trim());
  return rows.map((values) => Object.fromEntries(headers.map((header, index) => [header, (values[index] || "").trim()])));
}

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

function normalizeAnswer(value) {
  return value
    .toLowerCase()
    .replace(/[«»"'.!?;:]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function shuffle(items) {
  const copy = [...items];
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
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

function exerciseLevel(exercise) {
  const word = wordForExercise(exercise);
  return word ? word.word_level : exercise.word_level;
}

function wordForExercise(exercise) {
  return state.words.find((item) => item.word === exercise.word);
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
    state.manifests = await fetch("assets/verbs.json").then((response) => response.json());
    loadSettings();
    renderVerbSelect();
    await loadVerb(state.manifests[0].base);
    bindEvents();
  } catch (error) {
    document.body.insertAdjacentHTML("afterbegin", `<div class="error-state">${error.message}</div>`);
  }
}

function bindEvents() {
  els.verbSelect.addEventListener("change", () => loadVerb(els.verbSelect.value));
  els.wordSearch.addEventListener("input", renderWords);
  els.translationEn.addEventListener("change", handleTranslationSettingsChange);
  els.translationRu.addEventListener("change", handleTranslationSettingsChange);
  els.levelCheckboxes.forEach((input) => input.addEventListener("change", handleLevelSettingsChange));
  els.typeFilter.addEventListener("change", applyExerciseFilters);
  els.checkButton.addEventListener("click", checkAnswer);
  els.nextButton.addEventListener("click", nextExercise);
}

function renderVerbSelect() {
  els.verbSelect.innerHTML = state.manifests
    .map((item) => `<option value="${item.base}">${item.label}</option>`)
    .join("");
}

async function loadVerb(base) {
  const manifest = state.manifests.find((item) => item.base === base);
  if (!manifest) {
    return;
  }

  els.overviewText.textContent = "Daten werden geladen ...";
  const [wordText, exerciseText] = await Promise.all([
    loadText(manifest.enriched),
    loadText(manifest.exercises)
  ]);

  state.words = parseDelimited(wordText, "|").sort((a, b) => {
    const rankDiff = frequencyRank(a) - frequencyRank(b);
    return rankDiff || a.word.localeCompare(b.word, "de");
  });
  state.exercises = parseDelimited(exerciseText, ",");
  resetExerciseProgress();
  renderOverview(manifest);
  renderWords();
  renderFilters();
  applyExerciseFilters();
}

function renderOverview(manifest) {
  updateStats();
  els.overviewText.textContent = `Das Set „${manifest.label}“ zeigt das Grundverb, abgeleitete Formen, Nomen aus derselben Wortfamilie und passende Übungen zu Übersetzung, Synonymen, Sätzen und Wortbildung.`;
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
      ...languages.map((language) => language === "en" ? word.word_translation_en : word.word_translation_ru),
      ...languages.map((language) => language === "en" ? word.sentence_example_translation_en : word.sentence_example_translation_ru)
    ].join(" ").toLowerCase();
    return haystack.includes(query);
  });

  if (visibleWords.length === 0) {
    const colspan = languages.length > 0 ? 6 : 5;
    els.wordTableBody.innerHTML = `<tr><td colspan="${colspan}" class="empty-cell">Keine Treffer.</td></tr>`;
    return;
  }

  els.wordTableBody.innerHTML = visibleWords.map((word) => `
    <tr class="${isLevelActive(word.word_level) ? "" : "inactive-row"}">
      <th scope="row">${escapeHtml(word.word)}</th>
      <td><span class="level">${escapeHtml(word.word_level || "-")}</span></td>
      ${languages.length > 0 ? `<td class="translation-column">${renderTranslationLines(word, "word")}</td>` : ""}
      <td>${escapeHtml(word.word_synonyms || "-")}</td>
      <td>${renderExampleLines(word)}</td>
      <td>${escapeHtml(word.sentence_synonym || "-")}</td>
    </tr>
  `).join("");
}

function renderFilters() {
  const selectedType = els.typeFilter.value;
  const activeExercises = availableExercises();
  const types = unique(activeExercises.map((exercise) => exercise.type));

  els.typeFilter.innerHTML = '<option value="">Alle Typen</option>' + types
    .map((type) => `<option value="${escapeHtml(type)}">${escapeHtml(typeLabels[type] || type)}</option>`)
    .join("");

  if (types.includes(selectedType)) {
    els.typeFilter.value = selectedType;
  }
}

function applyExerciseFilters() {
  const type = els.typeFilter.value;
  state.filteredExercises = shuffle(availableExercises().filter((exercise) => !type || exercise.type === type));
  updateStats();
  resetExerciseProgress();
  renderExercise();
}

function activeLevelExercises() {
  return state.exercises.filter((exercise) => isLevelActive(exerciseLevel(exercise)));
}

function availableExercises() {
  return activeLevelExercises().filter(isExerciseLanguageEnabled);
}

function isExerciseLanguageEnabled(exercise) {
  const languages = selectedTranslations();

  if (exercise.type.includes("_en") && !languages.includes("en")) {
    return false;
  }
  if (exercise.type.includes("_ru") && !languages.includes("ru")) {
    return false;
  }

  return true;
}

function handleTranslationSettingsChange() {
  saveSettings();
  renderWords();
  renderFilters();
  applyExerciseFilters();
}

function renderForSettings() {
  renderWords();
  renderExercise();
}

function handleLevelSettingsChange() {
  saveSettings();
  renderWords();
  renderFilters();
  applyExerciseFilters();
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
      return { translations: ["en", "ru"], levels: DEFAULT_LEVELS };
    }
    const parsed = JSON.parse(raw);
    return {
      translations: Array.isArray(parsed.translations) ? parsed.translations : ["en", "ru"],
      levels: Array.isArray(parsed.levels) ? parsed.levels : DEFAULT_LEVELS
    };
  } catch (error) {
    return { translations: ["en", "ru"], levels: DEFAULT_LEVELS };
  }
}

function saveSettings() {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify({
      translations: selectedTranslations(),
      levels: [...activeLevels()]
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
  els.exerciseCount.textContent = availableExercises().length;
  els.levelRange.textContent = levels.length > 1 ? `${levels[0]}-${levels[levels.length - 1]}` : levels[0] || "-";
}

function resetExerciseProgress() {
  state.currentIndex = 0;
  state.correctCount = 0;
  state.selectedAnswer = "";
  state.sentenceParts = [];
  state.answeredIds = new Set();
}

function currentExercise() {
  return state.filteredExercises[state.currentIndex];
}

function renderExercise() {
  const exercise = currentExercise();
  state.selectedAnswer = "";
  state.sentenceParts = [];
  els.feedback.textContent = "";
  els.feedback.className = "feedback";
  els.checkButton.disabled = false;

  updateProgress();

  if (!exercise) {
    els.exerciseType.textContent = "-";
    els.exerciseWord.textContent = "-";
    els.questionText.textContent = "Keine Übungen für diesen Filter.";
    els.answerArea.innerHTML = "";
    els.exampleDe.textContent = "";
    els.exampleRu.textContent = "";
    els.exampleEn.textContent = "";
    els.exampleRu.hidden = true;
    els.exampleEn.hidden = true;
    els.checkButton.disabled = true;
    return;
  }

  els.exerciseType.textContent = typeLabels[exercise.type] || exercise.type;
  els.exerciseWord.textContent = exercise.word;
  els.questionText.textContent = exerciseQuestion(exercise);
  els.exampleDe.textContent = exercise.sentence_example || "";
  renderExerciseTranslations(exercise);

  if (exercise.type === "sentence_order") {
    renderSentenceOrder(exercise);
  } else if (hasOptions(exercise)) {
    renderOptions(exercise);
  } else {
    renderTextInput();
  }
}

function hasOptions(exercise) {
  return [exercise.option_1, exercise.option_2, exercise.option_3, exercise.option_4].some(Boolean);
}

function renderOptions(exercise) {
  const options = unique([exercise.option_1, exercise.option_2, exercise.option_3, exercise.option_4]);
  els.answerArea.innerHTML = options.map((option) => `
    <button class="option-button" type="button" data-answer="${escapeHtml(option)}">${escapeHtml(option)}</button>
  `).join("");

  els.answerArea.querySelectorAll(".option-button").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedAnswer = button.dataset.answer;
      els.answerArea.querySelectorAll(".option-button").forEach((item) => item.classList.remove("selected"));
      button.classList.add("selected");
    });
  });
}

function renderTextInput() {
  els.answerArea.innerHTML = '<input id="textAnswer" type="text" autocomplete="off" placeholder="Antwort eingeben" aria-label="Antwort">';
  document.querySelector("#textAnswer").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      checkAnswer();
    }
  });
}

function renderSentenceOrder(exercise) {
  const parts = (exercise.extra || exercise.correct_answer).split("|").map((part) => part.trim()).filter(Boolean);
  els.answerArea.innerHTML = `
    <div class="sentence-builder" id="sentenceBuilder" aria-label="Zusammengesetzter Satz"></div>
    <div class="sentence-bank" id="sentenceBank" aria-label="Wörter zur Auswahl">
      ${parts.map((part, index) => `<button class="word-chip" type="button" data-index="${index}" data-word="${escapeHtml(part)}">${escapeHtml(part)}</button>`).join("")}
    </div>
  `;

  els.answerArea.querySelectorAll(".word-chip").forEach((button) => {
    button.addEventListener("click", () => {
      state.sentenceParts.push(button.dataset.word);
      button.disabled = true;
      renderSentenceBuilder();
    });
  });
}

function renderSentenceBuilder() {
  const builder = document.querySelector("#sentenceBuilder");
  builder.innerHTML = state.sentenceParts.map((part, index) => `
    <button class="word-chip" type="button" data-index="${index}">${escapeHtml(part)}</button>
  `).join("");

  builder.querySelectorAll(".word-chip").forEach((button) => {
    button.addEventListener("click", () => {
      const [removed] = state.sentenceParts.splice(Number(button.dataset.index), 1);
      const bankButton = [...document.querySelectorAll("#sentenceBank .word-chip")]
        .find((item) => item.dataset.word === removed && item.disabled);
      if (bankButton) {
        bankButton.disabled = false;
      }
      renderSentenceBuilder();
    });
  });
}

function checkAnswer() {
  const exercise = currentExercise();
  if (!exercise) {
    return;
  }

  const answer = getAnswer(exercise);
  if (!answer) {
    showFeedback("Bitte eine Antwort eingeben oder auswählen.", false);
    return;
  }

  const accepted = unique((exercise.accepted_answers || exercise.correct_answer).split("|").map((item) => item.trim()));
  const isCorrect = accepted.some((acceptedAnswer) => normalizeAnswer(acceptedAnswer) === normalizeAnswer(answer));

  if (isCorrect && !state.answeredIds.has(exercise.exercise_id)) {
    state.correctCount += 1;
    state.answeredIds.add(exercise.exercise_id);
  }

  const message = isCorrect
    ? `Richtig. ${exerciseHint(exercise)}`
    : `Nicht richtig. Richtige Antwort: ${exercise.correct_answer}. ${exerciseHint(exercise)}`;

  showFeedback(message.trim(), isCorrect);
  updateProgress();
}

function getAnswer(exercise) {
  if (exercise.type === "sentence_order") {
    return state.sentenceParts.join(" ");
  }
  const input = document.querySelector("#textAnswer");
  return input ? input.value : state.selectedAnswer;
}

function showFeedback(message, isCorrect) {
  els.feedback.textContent = message;
  els.feedback.className = `feedback ${isCorrect ? "correct" : "wrong"}`;
}

function nextExercise() {
  if (state.filteredExercises.length === 0) {
    return;
  }
  state.currentIndex = (state.currentIndex + 1) % state.filteredExercises.length;
  renderExercise();
}

function updateProgress() {
  const total = state.filteredExercises.length;
  const current = total === 0 ? 0 : state.currentIndex + 1;
  const width = total === 0 ? 0 : (current / total) * 100;
  els.progressText.textContent = `${current} / ${total}`;
  els.progressBar.style.width = `${width}%`;
  els.scoreText.textContent = `Richtig: ${state.correctCount}`;
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

function renderExerciseTranslations(exercise) {
  const languages = selectedTranslations();
  els.exampleEn.hidden = !languages.includes("en");
  els.exampleRu.hidden = !languages.includes("ru");
  els.exampleEn.textContent = languages.includes("en") ? exercise.sentence_example_translation_en || "" : "";
  els.exampleRu.textContent = languages.includes("ru") ? exercise.sentence_example_translation_ru || "" : "";
}

function exerciseQuestion(exercise) {
  const word = wordForExercise(exercise);

  switch (exercise.type) {
    case "multiple_choice_de_en":
      return `Welche englische Übersetzung passt zu „${exercise.word}“?`;
    case "multiple_choice_ru_de":
      return `Wie heißt „${word?.word_translation_ru || exercise.word}“ auf Deutsch?`;
    case "multiple_choice_synonym":
      return `Wähle ein deutsches Synonym oder ein nah verwandtes Wort für „${exercise.word}“.`;
    case "sentence_translation_de_en":
      return `Übersetze den Satz ins Englische: „${exercise.sentence_example}“`;
    case "sentence_translation_de_ru":
      return `Übersetze den Satz ins Russische: „${exercise.sentence_example}“`;
    case "sentence_order":
      return "Setze den deutschen Satz aus den Wörtern zusammen.";
    case "multiple_choice_sentence_paraphrase":
      return `Wähle die passende Paraphrase für: „${exercise.sentence_example}“`;
    case "word_family_base":
      return `Von welchem Grundwort ist „${exercise.word}“ abgeleitet?`;
    default:
      return "Löse die Übung.";
  }
}

function exerciseHint(exercise) {
  switch (exercise.type) {
    case "multiple_choice_de_en":
      return "Wähle die englische Bedeutung des deutschen Wortes.";
    case "multiple_choice_ru_de":
      return "Wähle das passende deutsche Wort.";
    case "multiple_choice_synonym":
      return "Synonyme können je nach Kontext variieren.";
    case "sentence_translation_de_en":
    case "sentence_translation_de_ru":
      return "Achte auf die Bedeutung des ganzen Satzes.";
    case "sentence_order":
      return "Die Wortstellung muss dem Beispielsatz entsprechen.";
    case "multiple_choice_sentence_paraphrase":
      return "Die richtige Option gibt dieselbe Bedeutung mit anderen Worten wieder.";
    case "word_family_base":
      return "Gesucht ist das Grundwort der Wortfamilie.";
    default:
      return "";
  }
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
