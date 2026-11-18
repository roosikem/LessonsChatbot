const tokenInput = document.getElementById("token");
const mappingBody = document.querySelector("#mapping tbody");
const filtersBox = document.getElementById("filters");

let upload = null;     // last upload response
let knownDims = [];    // dimensions in the current index, to highlight new ones

try { tokenInput.value = sessionStorage.getItem("adminToken") || ""; } catch {}
tokenInput.addEventListener("change", () => {
  try { sessionStorage.setItem("adminToken", tokenInput.value); } catch {}
  loadCurrent();
});

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

async function api(path, options = {}) {
  const resp = await fetch(path, {
    ...options,
    headers: { ...(options.headers || {}), "X-Admin-Token": tokenInput.value },
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || `${resp.status} ${resp.statusText}`);
  return body;
}

async function loadCurrent() {
  const info = document.getElementById("current-info");
  const dims = document.getElementById("current-dims");
  try {
    const cur = await api("/api/admin/current");
    if (!cur.version) {
      info.textContent = "No index yet.";
      return;
    }
    knownDims = Object.keys(cur.dimensions);
    const items = Object.entries(cur.context_items || {}).map(([source, n]) => `${n} ${source}`).join(" · ");
    info.textContent = `Version ${cur.version} · ${cur.lessons} lessons · ${items || "no context sources"} · embeddings ${cur.embedding_model}`;
    dims.replaceChildren(...knownDims.map((d) => el("span", "", d)));
  } catch (e) {
    info.textContent = e.message;
  }
}

document.getElementById("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = document.getElementById("upload-error");
  err.textContent = "";
  const form = new FormData();
  form.append("file", document.getElementById("file").files[0]);
  const sheet = document.getElementById("sheet").value.trim();
  if (sheet) form.append("sheet", sheet);
  form.append("header_row", document.getElementById("header-row").value || "1");
  try {
    upload = await api("/api/admin/uploads", { method: "POST", body: form });
    renderMapping();
  } catch (ex) {
    err.textContent = ex.message;
  }
});

function renderMapping() {
  const stats = Object.fromEntries(upload.profile.columns.map((c) => [c.column, c]));
  document.getElementById("profile-info").textContent =
    `${upload.filename}: ${upload.profile.rows} rows, ${upload.profile.columns.length} columns. ✓ = column known from the current mapping.`;
  mappingBody.replaceChildren();

  for (const s of upload.suggestion) {
    const c = stats[s.column];
    const tr = el("tr", s.known ? "known" : "");
    tr.dataset.column = s.column;
    tr.append(el("td", "", s.column), el("td", "", `${c.filled}/${upload.profile.rows}`), el("td", "", c.distinct));
    const ex = el("td", "examples", c.top.map(([v]) => v).join(" · "));
    ex.title = c.top.map(([v, n]) => `${v} (${n})`).join("\n");
    tr.append(ex);

    const role = el("select", "role");
    for (const r of upload.roles) role.append(new Option(r, r, false, r === s.role));
    const dim = el("input", "dim");
    dim.value = s.dimension || "";
    dim.placeholder = "dimension";
    const sep = el("select", "sep");
    for (const [label, val] of [["—", ""], [";", ";"], ["|", "|"], ["line", "\n"], [",", ","]]) {
      sep.append(new Option(label, val, false, val === (s.separator || "")));
    }
    const sync = () => {
      const isContext = role.value === "context";
      const named = isContext || role.value === "ranking";  // ranking columns get a signal name
      dim.hidden = !named;
      sep.hidden = !isContext;
      if (named && !dim.value) dim.value = s.column.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
      tr.classList.toggle("ignored", role.value === "ignore");
      renderFilters();
    };
    role.onchange = sync;
    const tdRole = el("td"); tdRole.append(role);
    const tdDim = el("td"); tdDim.append(dim);
    const tdSep = el("td"); tdSep.append(sep);
    tr.append(tdRole, tdDim, tdSep);
    mappingBody.append(tr);
    dim.hidden = !["context", "ranking"].includes(s.role);
    sep.hidden = s.role !== "context";
    tr.classList.toggle("ignored", s.role === "ignore");
  }
  renderFilters();
  document.getElementById("mapping-card").hidden = false;
  document.getElementById("result-card").hidden = true;
}

function renderFilters() {
  const stats = Object.fromEntries(upload.profile.columns.map((c) => [c.column, c]));
  const previous = currentFilters();
  filtersBox.replaceChildren();
  for (const tr of mappingBody.querySelectorAll("tr")) {
    if (tr.querySelector(".role").value !== "filter") continue;
    const col = tr.dataset.column;
    const box = el("div", "filter");
    box.append(el("b", "", `${col}: keep only `));
    for (const value of stats[col].values || stats[col].top.map(([v]) => v)) {
      const label = el("label");
      const cb = el("input");
      cb.type = "checkbox";
      cb.value = value;
      const keep = (upload.keep_status_values || []).map((v) => v.toLowerCase());
      cb.checked = previous[col] ? previous[col].includes(value) : keep.includes(value.trim().toLowerCase());
      label.append(cb, " " + value);
      box.append(label);
    }
    box.dataset.column = col;
    filtersBox.append(box);
  }
}

function currentFilters() {
  const out = {};
  for (const box of filtersBox.querySelectorAll(".filter")) {
    out[box.dataset.column] = [...box.querySelectorAll("input:checked")].map((i) => i.value);
  }
  return out;
}

function currentRoles() {
  return [...mappingBody.querySelectorAll("tr")].map((tr) => ({
    column: tr.dataset.column,
    role: tr.querySelector(".role").value,
    dimension: tr.querySelector(".dim").value.trim() || null,
    separator: tr.querySelector(".sep").value || null,
  }));
}

document.getElementById("ingest-btn").addEventListener("click", async () => {
  const err = document.getElementById("mapping-error");
  const btn = document.getElementById("ingest-btn");
  err.textContent = "";
  btn.disabled = true;
  const result = document.getElementById("result");
  document.getElementById("result-card").hidden = false;
  result.replaceChildren(el("p", "spinner", "Cleaning, embedding and indexing"));
  try {
    const { job_id } = await api(`/api/admin/uploads/${upload.upload_id}/ingest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ roles: currentRoles(), filters: currentFilters() }),
    });
    let job;
    const giveUp = Date.now() + 30 * 60 * 1000;  // a large file can take a while, but not forever
    do {
      await new Promise((r) => setTimeout(r, 1500));
      job = await api(`/api/admin/jobs/${job_id}`);
      if (Date.now() > giveUp) throw new Error("The ingest is taking very long. Check the server log.");
    } while (job.status === "running");
    renderResult(job);
  } catch (e) {
    err.textContent = e.message;
    result.replaceChildren();
  } finally {
    btn.disabled = false;
  }
});

async function renderResult(job) {
  const box = document.getElementById("result");
  if (job.status === "failed") {
    box.replaceChildren(el("p", "error", job.error));
    return;
  }
  const r = job.result;
  const before = new Set(knownDims);
  await loadCurrent();
  const parts = [
    el("p", "ok", `New index ${r.version} is live: ${r.loaded} of ${r.rows} rows loaded.`),
  ];
  const added = knownDims.filter((d) => !before.has(d));
  const chips = el("div", "chips");
  for (const d of knownDims) chips.append(el("span", added.includes(d) ? "new" : "", d));
  parts.push(el("p", "muted", added.length ? `New context dimensions: ${added.join(", ")}` : "Context dimensions:"), chips);
  if (r.skipped && r.skipped.length) {
    parts.push(el("p", "", `Skipped ${r.skipped.length} rows:`));
    const ul = el("ul");
    for (const s of r.skipped) ul.append(el("li", "", `${s.id}: ${s.reason}`));
    parts.push(ul);
  }
  for (const [source, values] of Object.entries(r.unknown_links || {})) {
    parts.push(el("p", "error", `Lessons point to unknown ${source}: ${values.join(", ")}`));
  }
  if (r.graph?.error) parts.push(el("p", "error", r.graph.error));
  else if (r.graph) parts.push(el("p", "muted", `Neo4j rebuilt: ${r.graph.lessons} lessons, ${r.graph.relationships} relationships.`));
  box.replaceChildren(...parts);
}

async function loadName() {
  // the app name comes from the server config (APP_NAME or assistant.yaml), like on the chat page
  try {
    const name = (await (await fetch("/api/config")).json()).assistant?.app_name;
    if (name) {
      document.title = `${name} · Admin`;
      document.querySelector("header h1").textContent = `${name} · Admin`;
    }
  } catch {}
}

loadName();
loadCurrent();
