# DeutschSprint

DeutschSprint is a static web app for learning German vocabulary through verb families. Learners can explore a base verb and related words together, compare their meanings, and see how they are used in context. The project is designed to run on GitHub Pages without a backend.

## Features

- Browse and search for base verbs, and save favorites for later.
- Search the selected word family and filter it by CEFR level (A1–C2).
- Show or hide English and Russian translations.
- Explore examples, synonyms, paraphrases, collocations, and usage notes where available.
- Export the displayed vocabulary to an Excel file.

Settings, favorites, recent verbs, and cached data are stored in the browser's local storage.

## Run locally

The app uses plain HTML, CSS, and JavaScript and does not require a build step. Serve the repository over HTTP so the browser can load the data files, for example:

```sh
python3 -m http.server 8000
```

Open <http://localhost:8000/> in a browser. Stop the server with Ctrl+C.

## Project structure

- `index.html` — application markup.
- `styles.css` — presentation and responsive layout.
- `app.js` — data loading, filtering, browser storage, and export.
- `assets/verbs.json` — categorized index of base verbs and their data files.
- `assets/enriched/` — CSV vocabulary data for individual verb families.
- `.github/workflows/static.yml` — GitHub Pages deployment workflow.

To update a family, edit its CSV in `assets/enriched/`. When adding a family, also add an entry pointing to its CSV in the appropriate category in `assets/verbs.json`.

## Deployment

The GitHub Actions workflow deploys the repository as a static site when changes are pushed to `master`; it can also be run manually from the Actions tab. In the repository's Pages settings, select **GitHub Actions** as the deployment source. No build step or server-side application is needed.

## License

This project is released under the [Unlicense](LICENSE).
