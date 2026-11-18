const thread = document.getElementById("thread");
const form = document.getElementById("ask");
const input = document.getElementById("question");
const send = document.getElementById("send");
const debugBox = document.getElementById("debug");
const lessonTpl = document.getElementById("lesson-tpl");

let config = {};
let history = [];  // [{role, content}] sent back so follow-ups keep context

const TOOL_LABELS = {
  search_lessons: "Searching lessons",
  resolve_context: "Matching your terms to the data",
  comparable_items: "Finding comparable items",
  count_by: "Counting recurring topics",
  related_lessons: "Following graph connections",
};

const REASON_LABELS = {
  context_match: (r) => `${r.dimension}: ${r.value}`,
  same_item: (r) => `same ${r.source || "item"}: ${r.value}`,
  comparable_item: (r) => `comparable ${r.source || "item"}: ${r.value}`,
  similar_problem: (r) => `similar problem`,
  feedback: (r) => `helpful for similar questions (${r.value})`,
};

async function loadConfig() {
  config = await (await fetch("/api/config")).json();
  document.getElementById("model").textContent = `${config.llm} · ${config.search_store}`;
  if (config.debug) document.getElementById("debug-toggle").hidden = false;

  // wording and example questions come from config/assistant.yaml
  const a = config.assistant || {};
  if (a.app_name) {
    document.title = a.app_name;
    document.querySelector("header h1").textContent = a.app_name;
  }
  document.getElementById("tagline").textContent = a.tagline || "";
  input.placeholder = a.placeholder || "";
  const examples = document.querySelector(".examples");
  examples.replaceChildren(...(a.examples || []).map((ex) => {
    const b = el("button", "", ex.label);
    b.onclick = () => { if (!send.disabled) ask(ex.question); };  // one question at a time
    return b;
  }));
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function scrollDown() {
  thread.scrollTop = thread.scrollHeight;
}

function addUserMessage(text) {
  document.getElementById("welcome")?.remove();
  const msg = el("div", "msg user");
  msg.append(el("div", "bubble", text));
  thread.append(msg);
  scrollDown();
}

function stepLabel(event) {
  const label = TOOL_LABELS[event.tool] || event.tool;
  const detail = event.input?.query || event.input?.term || event.input?.name || event.input?.dimension || event.input?.id;
  return detail ? `${label}: "${detail}"` : label;
}

async function ask(question) {
  addUserMessage(question);
  const bot = el("div", "msg bot");
  const steps = el("ul", "steps");
  const status = el("li", "spinner", "Thinking");
  steps.append(status);
  bot.append(steps);
  thread.append(bot);
  scrollDown();

  send.disabled = true;
  try {
    const resp = await fetch("/api/ask/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history }),
    });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      throw new Error(resp.status === 422 ? "The question is too long or malformed." : body.detail || `${resp.status}`);
    }
    const ctx = { bot, steps, status, question, finished: false };
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let cut;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        if (!block.startsWith("data: ")) continue;  // ": ping" heartbeats
        handleEvent(JSON.parse(block.slice(6)), ctx);
      }
    }
    if (!ctx.finished) throw new Error("the connection closed before the answer arrived");
  } catch (err) {
    status.remove();
    bot.append(el("p", "error", `Something went wrong: ${err.message}`));
  } finally {
    send.disabled = false;
    input.focus();
  }
}

function handleEvent(event, ctx) {
  if (event.type === "tool") {
    ctx.steps.insertBefore(el("li", "", stepLabel(event)), ctx.status);
  } else if (event.type === "candidates") {
    // shown right away; the checked answer below replaces this list
    const li = el("li", "candidates", "Found: " + event.lessons.map((l) => `[${l.id}] ${l.title}`).join(" · "));
    ctx.steps.insertBefore(li, ctx.status);
  } else if (event.type === "cached") {
    ctx.steps.insertBefore(el("li", "", "Same question answered recently: showing that answer"), ctx.status);
  } else if (event.type === "grading") {
    ctx.steps.insertBefore(el("li", "", `Checking which of ${event.candidates} lessons really fit`), ctx.status);
  } else if (event.type === "writing") {
    ctx.status.textContent = `Writing the answer from ${event.lessons_found} lessons`;
  } else if (event.type === "answer") {
    ctx.finished = true;
    ctx.status.remove();
    renderAnswer(ctx.bot, event, ctx.question);
  } else if (event.type === "error") {
    ctx.finished = true;
    ctx.status.remove();
    ctx.bot.append(el("p", "error", event.message));
  }
  scrollDown();
}

function renderAnswer(bot, result, question) {
  const a = result.answer;
  if (a.clarifying_question) bot.append(el("div", "clarify", a.clarifying_question));
  if (a.summary) bot.append(el("p", "summary", a.summary));
  if (a.related_only) bot.append(el("div", "clarify", config.assistant?.related_only_text || "No direct match; these are related."));
  if (a.next_step) bot.append(el("div", "clarify", a.next_step));
  if (a.missing && a.lessons.length) bot.append(el("p", "notfound", `Not covered by these lessons: ${a.missing}`));
  if (result.not_found && !a.summary) bot.append(el("p", "notfound", "No matching lessons were found in the data."));

  for (const lesson of a.lessons) bot.append(renderLesson(lesson, result.id, question));

  if (config.feedback) bot.append(answerVotes(result.id, question));
  if (config.debug) {
    const dbg = el("pre", "debug", JSON.stringify({ tools: result.trace, checks: result.issues }, null, 2));
    dbg.hidden = !debugBox.checked;
    dbg.classList.add("debug-block");
    bot.append(dbg);
  }

  history.push({ role: "user", content: question.slice(0, 3900) });
  const memo = a.clarifying_question || [a.summary, ...a.lessons.map((l) => `[${l.id}] ${l.title}`)].join("\n");
  history.push({ role: "assistant", content: (memo || "(no answer)").slice(0, 3900) });
  history = history.slice(-8);
}

function renderLesson(lesson, answerId, question) {
  const node = lessonTpl.content.firstElementChild.cloneNode(true);
  node.querySelector(".lesson-id").textContent = lesson.id;
  node.querySelector("h3").textContent = lesson.title;
  const conf = node.querySelector(".confidence");
  conf.textContent = lesson.fit === "partial" ? `${lesson.confidence} · partial fit` : lesson.confidence;
  conf.classList.add(lesson.confidence);
  node.querySelector(".learning").textContent = lesson.learning;

  const reasons = node.querySelector(".reasons");
  for (const r of lesson.why_relevant) {
    const label = (REASON_LABELS[r.type] || (() => r.value))(r);
    const li = el("li", "", label);
    if (r.type === "similar_problem") li.title = r.value;
    reasons.append(li);
  }
  node.querySelector(".quote").textContent = lesson.quote ? `“${lesson.quote}”` : "";
  node.querySelector(".original-text").textContent = lesson.text;

  const dl = node.querySelector(".context");
  for (const [dim, values] of Object.entries(lesson.context)) {
    if (!values.length) continue;
    dl.append(el("dt", "", dim), el("dd", "", values.join(", ")));
  }

  if (config.graph) {
    const btn = node.querySelector(".related-btn");
    btn.hidden = false;
    btn.onclick = () => showRelated(lesson.id, node.querySelector(".related"), btn);
  }

  if (config.feedback) {
    for (const b of node.querySelectorAll(".vote")) {
      b.onclick = () => vote(b, { answer_id: answerId, question, vote: b.dataset.vote, lesson_id: lesson.id });
    }
  } else {
    node.querySelectorAll(".vote").forEach((b) => b.remove());
  }
  return node;
}

async function showRelated(id, box, btn) {
  btn.disabled = true;
  let data;
  try {
    const resp = await fetch(`/api/lessons/${encodeURIComponent(id)}/related`);
    if (!resp.ok) throw new Error(resp.status);
    data = await resp.json();
  } catch {
    box.replaceChildren(el("div", "error", "Could not load related lessons. Please try again."));
    btn.disabled = false;
    return;
  }
  const ul = el("ul");
  for (const r of data.related || []) {
    const li = el("li", "", `[${r.id}] ${r.title}`);
    li.title = r.why.join("\n");
    li.append(el("div", "", r.why.slice(0, 2).join(" · ")));
    ul.append(li);
  }
  box.replaceChildren(el("div", "", "Connected in the graph:"), ul);
}

function answerVotes(answerId, question) {
  const row = el("div", "answer-actions", "Was this answer helpful?");
  for (const [v, label] of [["up", "👍"], ["down", "👎"]]) {
    const b = el("button", "vote", label);
    b.onclick = () => vote(b, { answer_id: answerId, question, vote: v });
    row.append(b);
  }
  return row;
}

function voterId() {
  // a random id per browser, so one person's repeated clicks count once (SSO replaces it on the platform)
  try {
    let id = localStorage.getItem("voterId");
    if (!id) {
      id = Math.random().toString(36).slice(2) + Date.now().toString(36);
      localStorage.setItem("voterId", id);
    }
    return id;
  } catch {
    return null;
  }
}

async function vote(button, payload) {
  try {
    const resp = await fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...payload, voter: voterId() }),
    });
    if (!resp.ok) throw new Error(resp.status);
  } catch {
    button.dataset.title ??= button.title;
    button.title = "Your vote could not be saved. Please try again.";
    return;  // don't show it as chosen
  }
  if (button.dataset.title !== undefined) button.title = button.dataset.title;  // back to "Useful" / "Not relevant"
  button.parentElement.querySelectorAll(".vote").forEach((b) => b.classList.remove("chosen"));
  button.classList.add("chosen");
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const q = input.value.trim();
  if (!q || send.disabled) return;
  input.value = "";
  ask(q);
});

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});


document.getElementById("new-chat").onclick = () => location.reload();
debugBox.onchange = () => document.querySelectorAll(".debug-block").forEach((d) => (d.hidden = !debugBox.checked));

loadConfig();
