/* The console, in one file and no framework.
 *
 * Two rules it does not break:
 *
 * - **nothing is ever built from a string of HTML.** Ticket titles, session
 *   steps and command output all come from somewhere else — Notion, a repository,
 *   a shell — and every one of them lands in a `textContent`. There is no place
 *   in this file where text becomes markup;
 * - **the stream is the truth.** A click posts and says nothing; what appears on
 *   the screen is what came back on the event stream. So two open tabs show the
 *   same thing, and a message sent from a phone shows up on the laptop.
 */

const $ = (id) => document.getElementById(id);

const state = {
  board: { tickets: [], columns: [] },
  projects: [],
  info: {},
  busy: false,
  running: null,   // the steps block of the turn in flight
  command: null,   // the <pre> of the command in flight
  sessions: new Map(),
};

/* -- talking to the server -------------------------------------------------- */

async function api(path, body) {
  const options = body
    ? {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Ticket-Runner": "1" },
        body: JSON.stringify(body),
      }
    : { headers: { "X-Ticket-Runner": "1" } };
  const response = await fetch(path, { ...options, credentials: "same-origin" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `${response.status}`);
  return payload;
}

function connect() {
  const stream = new EventSource("/api/events", { withCredentials: true });
  const mark = (text, className) => {
    const node = $("connection");
    node.textContent = text;
    node.className = `link ${className}`;
  };
  stream.onopen = () => mark("live", "on");
  stream.onerror = () => mark("reconnecting…", "off");
  stream.addEventListener("board", (event) => renderBoard(JSON.parse(event.data)));
  stream.addEventListener("step", (event) => onStep(JSON.parse(event.data)));
  stream.addEventListener("chat", (event) => onChat(JSON.parse(event.data)));
  stream.addEventListener("command", (event) => onCommand(JSON.parse(event.data)));
  // "notice", not "error": EventSource fires an `error` event of its own for
  // every dropped connection, and a server event under the same name would
  // arrive through the same listener with nothing in it.
  stream.addEventListener("notice", (event) => {
    const payload = JSON.parse(event.data);
    say("error", `${payload.where}: ${payload.message}`);
  });
}

/* -- the board -------------------------------------------------------------- */

const LABEL = {
  ready: "Ready", running: "In progress", review: "In review",
  blocked: "Blocked", failed: "Failed", done: "Done", other: "Elsewhere",
};

function renderBoard(board) {
  state.board = board;
  const host = $("columns");
  host.textContent = "";
  const groups = new Map();
  for (const ticket of board.tickets) {
    if (!groups.has(ticket.column)) groups.set(ticket.column, []);
    groups.get(ticket.column).push(ticket);
  }
  // Done is real but it is not news: it would be most of the board within a
  // week, and push everything worth looking at below the fold.
  const order = ["ready", "running", "review", "blocked", "failed", "other"];
  for (const key of order) {
    const tickets = groups.get(key) || [];
    if (!tickets.length && key !== "ready") continue;
    const column = element("div", "column");
    const heading = element("h2");
    heading.append(
      textNode(board.columns.find((c) => c.key === key)?.name || LABEL[key] || key),
      element("span", "count", String(tickets.length)),
    );
    column.append(heading);
    const cards = element("div", "cards");
    if (!tickets.length) cards.append(element("p", "empty", "Nothing ready. Write a ticket above."));
    for (const ticket of tickets) cards.append(card(ticket));
    column.append(cards);
    host.append(column);
  }
  const done = (groups.get("done") || []).length;
  if (done) host.append(element("p", "empty", `${done} done, kept in Notion.`));
}

function card(ticket) {
  const node = element("div", `card ${ticket.column}`);
  node.append(element("div", "title", ticket.title));

  const meta = element("div", "meta");
  if (ticket.project) meta.append(element("span", `tag ${ticket.kind}`, ticket.project));
  else meta.append(element("span", "tag document", "no project — document"));
  for (const [value, extra] of [[ticket.priority, ticket.priority], [ticket.model, ""]]) {
    if (value) meta.append(element("span", `tag ${extra}`, value));
  }
  if (ticket.scheduled) meta.append(element("span", "tag", `⏱ ${ticket.scheduled.replace("T", " ")}`));
  if (typeof ticket.cost === "number" && ticket.cost)
    meta.append(element("span", "tag", `$${ticket.cost.toFixed(2)}`));
  node.append(meta);

  if (ticket.progress) node.append(element("div", "progress", ticket.progress));

  const actions = element("div", "actions");
  actions.append(link("Notion", ticket.url));
  if (ticket.pull_request) actions.append(link("pull request", ticket.pull_request));
  if (ticket.session_link) actions.append(link("session", ticket.session_link));
  if (ticket.column !== "ready" && ticket.column !== "running")
    actions.append(action(ticket.column === "review" ? "run again" : "make ready", () => move(ticket, "ready")));
  if (ticket.column === "review") actions.append(action("done", () => move(ticket, "done")));
  if (ticket.column === "ready") actions.append(action("hold", () => move(ticket, "blocked")));
  node.append(actions);
  return node;
}

async function move(ticket, column) {
  try {
    await api(`/api/tickets/${ticket.id}/status`, { column });
  } catch (error) {
    say("error", `could not move “${ticket.title}”: ${error.message}`);
  }
}

/* -- the transcript --------------------------------------------------------- */

function say(role, text) {
  const turn = element("div", `turn ${role}`);
  turn.append(element("div", "who", role === "you" ? "you" : role === "error" ? "problem" : "workspace"));
  turn.append(element("div", "text", text));
  $("transcript").append(turn);
  scroll();
  return turn;
}

function scroll() {
  const view = $("transcript");
  view.scrollTop = view.scrollHeight;
}

function onChat(event) {
  if (event.stage === "reset") {
    $("transcript").textContent = "";
    welcome();
    return;
  }
  if (event.stage === "sent") {
    say("you", event.text);
    state.running = element("div", "steps");
    $("transcript").append(state.running);
    setBusy(true);
    return;
  }
  if (event.stage === "step") {
    if (!state.running) {
      state.running = element("div", "steps");
      $("transcript").append(state.running);
    }
    const line = element("div");
    line.append(element("span", "label", event.label));
    if (event.detail) line.append(textNode(` ${event.detail}`));
    state.running.append(line);
    state.running.scrollTop = state.running.scrollHeight;
    scroll();
    return;
  }
  if (event.stage === "answer" || event.stage === "failed") {
    if (state.running) state.running.classList.add("done");
    state.running = null;
    setBusy(false);
    say(event.stage === "answer" && event.ok !== false ? "workspace" : "error", event.text);
    if (event.cost_usd) {
      const note = element("div", "dim small", `${event.seconds}s · $${event.cost_usd}`);
      $("transcript").append(note);
    }
    refreshState();
  }
}

function onCommand(event) {
  if (event.stage === "started") {
    const turn = element("div", "turn command");
    turn.append(element("div", "who", `ticket-runner ${event.argv.join(" ")}`));
    state.command = element("div", "text");
    turn.append(state.command);
    $("transcript").append(turn);
    setBusy(true);
    scroll();
    return;
  }
  if (!state.command) return;
  if (event.stage === "line") {
    state.command.append(textNode(`${event.text}\n`));
    scroll();
    return;
  }
  if (event.stage === "ended") {
    if (event.code) state.command.append(textNode(`\n[exit ${event.code}]`));
    state.command = null;
    setBusy(false);
    refreshState();
  }
}

function onStep(event) {
  if (!state.sessions.has(event.source)) {
    const box = element("div", "session");
    box.append(element("h3", null, event.source));
    const list = element("div", "steps");
    box.append(list);
    $("sessions").prepend(box);
    state.sessions.set(event.source, list);
  }
  const list = state.sessions.get(event.source);
  const line = element("div");
  line.append(element("span", "label", event.label));
  if (event.detail) line.append(textNode(` ${event.detail}`));
  list.append(line);
  while (list.childElementCount > 200) list.firstElementChild.remove();
  list.scrollTop = list.scrollHeight;
}

/* -- the composer ----------------------------------------------------------- */

function isCommand(text) {
  return text.trimStart().startsWith(">");
}

function setBusy(busy) {
  state.busy = busy;
  $("send").disabled = busy;
  $("send").textContent = busy ? "working…" : "Send";
}

async function submit() {
  const field = $("input");
  const text = field.value.trim();
  if (!text || state.busy) return;
  field.value = "";
  resize();
  try {
    if (isCommand(text)) await api("/api/command", { line: text.replace(/^\s*>/, "") });
    else await api("/api/chat", { text });
  } catch (error) {
    say("error", error.message);
    setBusy(false);
  }
}

function resize() {
  const field = $("input");
  field.style.height = "auto";
  field.style.height = `${Math.min(field.scrollHeight, 200)}px`;
  field.classList.toggle("command", isCommand(field.value));
  $("hint").textContent = isCommand(field.value)
    ? `a ticket-runner command · ${(state.info.commands || []).join(" · ")}`
    : "a sentence talks to your workspace · > runs a ticket-runner command";
}

/* -- the header ------------------------------------------------------------- */

async function refreshState() {
  try {
    state.info = await api("/api/state");
  } catch (error) {
    return;
  }
  const info = state.info;
  const pills = $("pills");
  pills.textContent = "";
  const add = (text, className) => pills.append(element("span", `pill ${className || ""}`, text));
  add(info.timer === "enabled" ? `timer on · ${every(info.interval_seconds)}` : `timer ${info.timer}`,
      info.timer === "enabled" ? "on" : "warn");
  if (info.running) add("a run is in progress", "busy");
  if (!info.claude) add("claude not found", "warn");
  add(`${info.handled} handled · $${info.spend}`);
  add(info.version);
  $("chat-state").textContent = info.chat.session_id
    ? `${info.chat.turns} turn(s) · ${info.chat.resume_command}`
    : "no conversation yet";
}

function every(seconds) {
  if (!seconds) return "";
  return seconds < 120 ? `${seconds}s` : `${Math.round(seconds / 60)} min`;
}

/* -- little DOM helpers ----------------------------------------------------- */

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function textNode(text) {
  return document.createTextNode(text);
}

function link(label, href) {
  const node = document.createElement("a");
  node.textContent = label;
  node.href = href;
  node.target = "_blank";
  node.rel = "noreferrer noopener";
  return node;
}

function action(label, handler) {
  const node = element("button", null, label);
  node.addEventListener("click", handler);
  return node;
}

function welcome() {
  say(
    "workspace",
    "Ask me anything about your workspace — I can read your repositories, look at the board " +
      "and create tickets. Type > followed by a command (>status, >list, >run) to use the CLI directly.",
  );
}

/* -- wiring ----------------------------------------------------------------- */

async function boot() {
  document.querySelectorAll(".tabs button").forEach((button) => {
    button.addEventListener("click", () => show(button.dataset.pane));
  });
  show("board");

  $("input").addEventListener("input", resize);
  $("input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  });
  $("send").addEventListener("click", submit);
  $("reset").addEventListener("click", async () => {
    try {
      await api("/api/chat/reset", {});
    } catch (error) {
      say("error", error.message);
    }
  });
  $("refresh").addEventListener("click", () => api("/api/refresh", {}).catch(() => {}));

  $("new-title").addEventListener("focus", () => { $("compose-more").hidden = false; });
  $("new-title").addEventListener("keydown", (event) => {
    if (event.key === "Enter") create();
  });
  $("create").addEventListener("click", create);

  await refreshState();
  await loadChat();
  await loadProjects();
  connect();
}

async function loadChat() {
  try {
    const payload = await api("/api/chat");
    for (const message of payload.messages) say(message.role, message.text);
    if (!payload.messages.length) welcome();
    if (payload.busy) setBusy(true);
  } catch (error) {
    say("error", error.message);
  }
}

async function loadProjects() {
  try {
    const payload = await api("/api/projects");
    state.projects = payload.projects;
    const select = $("new-project");
    for (const project of payload.projects) {
      const option = document.createElement("option");
      option.value = project.id;
      option.textContent = `${project.name} — ${project.kind}`;
      select.append(option);
    }
  } catch (error) { /* a board with no projects database is a board that runs */ }
}

async function create() {
  const title = $("new-title").value.trim();
  if (!title) return;
  try {
    await api("/api/tickets", {
      title,
      body: $("new-body").value,
      project: $("new-project").value,
      ready: $("new-ready").checked,
    });
    $("new-title").value = "";
    $("new-body").value = "";
    $("compose-more").hidden = true;
  } catch (error) {
    say("error", `could not create the ticket: ${error.message}`);
    show("console");
  }
}

function show(pane) {
  document.querySelectorAll(".tabs button").forEach((button) => {
    button.classList.toggle("on", button.dataset.pane === pane);
  });
  for (const name of ["board", "console", "live"]) {
    $(`pane-${name}`).classList.toggle("showing", name === pane);
  }
  // On a wide screen the console is always the right-hand column, whichever of
  // the other two is chosen — so choosing one must not take it away.
  if (window.matchMedia("(min-width: 861px)").matches) {
    $("pane-console").classList.add("showing");
  }
}

boot();
