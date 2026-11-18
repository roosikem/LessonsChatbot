# `frontend/index.html`

> The chat page: the empty skeleton (header, message thread, question box) and the hidden template for one lesson card.

**Part of:** [Ask a question](../../flows/ask-a-question.md) · [Feedback](../../flows/feedback.md)  ·  **Layer:** UI

## Purpose
Users ask their question here, for example "We keep getting faults on site after software updates". The page itself holds almost no text. The app name, tagline, placeholder and example questions are filled in by [`app.js`](app.js.md) from the server, so another team can reuse the page by changing [`assistant.yaml`](../backend/config/assistant.yaml.md) only.

## How it works
1. The browser loads `/`. The API returns this file ([`api.py`](../backend/app/api.md), route `@app.get("/")`).
2. It loads `/static/style.css` and `/static/app.js`. `/static` is the `frontend/` folder, served by FastAPI.
3. `app.js` fills the header and the example buttons, then adds messages to `<main id="thread">` as the user chats.
4. For each lesson in an answer, `app.js` copies the `<template id="lesson-tpl">` and fills it.

## Key components
- `<header>`: title (`h1`), `#tagline`, `#model` pill (shows the model and search store), `#debug-toggle` checkbox (hidden unless the debug panel is on), `#new-chat` button.
- `<main id="thread">` with `#welcome`: the welcome text and the `.examples` box for example-question buttons. Removed when the first question is sent.
- `<form id="ask">`: the `#question` textarea and the `#send` button.
- `<template id="lesson-tpl">`: one lesson card. Parts: `.lesson-id`, `h3` (title), `.confidence`, `.learning`, `.reasons` (the "why relevant" chips), `.quote`, a `<details>` "Original entry" with `.original-text` and the `.context` list, then `.lesson-actions` with the "Related lessons" button (hidden by default) and two `.vote` buttons (👍 `data-vote="up"` with tooltip "Useful", 👎 `data-vote="down"` with tooltip "Not relevant"), and an empty `.related` box.

A `<template>` is HTML the browser keeps but does not show; code copies it to make real elements.

## Configuration
None in the file itself. What becomes visible depends on `/api/config`, see [`app.js`](app.js.md): `FEATURE_DEBUG_PANEL` shows the details toggle, `FEATURE_FEEDBACK` keeps the vote buttons, `FEATURE_NEO4J=true` (a graph agent) shows "Related lessons".

## Dependencies
- **Used by:** [`backend/app/api.py`](../backend/app/api.md) serves it at `/`.
- **Uses:** [`style.css`](style.css.md), [`app.js`](app.js.md).

## Example
With the default [`assistant.yaml`](../backend/config/assistant.yaml.md) the user sees the title "Talk to Lessons Learned", the tagline "Describe your situation. Get what earlier projects learned." and four buttons such as "Project: new metro line", which asks about commissioning on Valoria Metro Line 5.

## Known limitations and improvements
- The textarea has `rows="1"` and no `maxlength`. The API rejects questions over 2000 characters (422) and `app.js` shows a message, but the user only learns after sending. Idea: add `maxlength="2000"`.
- The textarea does not grow with the text (no auto-resize code); long questions scroll inside one line. Idea: a small auto-height handler.
- No `<noscript>` text: without JavaScript the page is empty.
