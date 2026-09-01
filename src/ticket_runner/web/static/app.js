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
  // The ticket whose terminal is open, as the board last described it, plus the
  // steps block its running session writes into.
  ticket: null,
  ticketSteps: null,
  // The settings tab. `edited` holds only what you actually touched: a field
  // left alone is a line the file keeps, comment and all — and a token you did
  // not retype is a token that never left the machine.
  settings: { drawn: null, edited: new Map(), projects: null },
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
  stream.addEventListener("talk", (event) => onTalk(JSON.parse(event.data)));
  // Another tab saved, or `ticket-runner config` did. Redraw — unless this tab
  // is in the middle of an edit, which is not something to take away from you.
  stream.addEventListener("settings", () => {
    if (!state.settings.edited.size && !state.settings.projects) loadSettings();
    refreshState();
  });
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
  validated: "Validated", blocked: "Blocked", failed: "Failed",
  done: "Done", other: "Elsewhere",
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
  const order = ["ready", "running", "review", "validated", "blocked", "failed", "other"];
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
  refreshTicket(board);
}

function card(ticket) {
  const node = element("div", `card ${ticket.column}`);
  // The card is the way into the ticket's terminal — except where it already
  // carries a gesture of its own: a click on "validate" is not a click on the
  // card it happens to sit in.
  node.tabIndex = 0;
  node.title = "open this ticket’s terminal";
  node.addEventListener("click", (event) => {
    if (!event.target.closest("a, button")) openTicket(ticket);
  });
  node.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.target === node) openTicket(ticket);
  });
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
  // The whole card opens it too; this is the one you can reach with a keyboard
  // and the one that says the terminal is there at all.
  actions.append(action("terminal", () => openTicket(ticket)));
  actions.append(link("Notion", ticket.url));
  if (ticket.pull_request) actions.append(link("pull request", ticket.pull_request));
  if (ticket.session_link) actions.append(link("session", ticket.session_link));
  if (ticket.column !== "ready" && ticket.column !== "running")
    actions.append(action(ticket.column === "review" ? "run again" : "make ready", () => move(ticket, "ready")));
  // Validating is the gesture the runner acts on — it merges the pull request,
  // or publishes what the ticket holds — where "done" only files the ticket
  // away yourself. Offered only on a board that has the column.
  if (ticket.column === "review" && state.board.validate)
    actions.append(action("validate", () => move(ticket, "validated")));
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
  turn.append(flow(element("div", "text"), text));
  $("transcript").append(turn);
  scroll();
  return turn;
}

function scroll(view = $("transcript")) {
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
    state.running.append(step(event));
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
    flow(state.command, `${event.text}\n`);
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
  list.append(step(event));
  while (list.childElementCount > 200) list.firstElementChild.remove();
  list.scrollTop = list.scrollHeight;
  // The same step, in the terminal of the ticket it belongs to — so that
  // reading a ticket and watching it work are one place rather than two.
  if (state.ticket && event.source === state.ticket.short) ticketStep(event);
}

/** One line of a session: the tool it used, and what it used it on. */
function step(event) {
  const line = element("div");
  line.append(element("span", "label", event.label));
  if (event.detail) flow(line, ` ${event.detail}`);
  return line;
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

/* -- one ticket's terminal ---------------------------------------------------
 *
 * The console's two halves — a transcript and a field — pointed at a single
 * ticket. What you type is a comment on it, and a comment is already how a
 * ticket is answered: a reply under the question a run asked puts the ticket
 * back in the queue, and one that names the runner asks it for words instead.
 * So there is nothing new to learn here, and nothing kept on the side: the
 * discussion is Notion's, and the same words typed into Notion do the same.
 */

async function openTicket(ticket, options = {}) {
  const another = !state.ticket || state.ticket.id !== ticket.id;
  state.ticket = ticket;
  if (another) state.ticketSteps = null;
  drawTicketHead(ticket);
  if (!options.keepPane) show("ticket");
  await loadTalk(ticket);
}

/** The board moved: keep the open ticket's terminal describing the right one. */
function refreshTicket(board) {
  if (!state.ticket) return;
  const fresh = board.tickets.find((item) => item.id === state.ticket.id);
  if (!fresh) return;
  // Reread the discussion only when the ticket *moved*: that is when a run
  // ended and left its report under it. A ticket in flight redraws the board
  // every few seconds, and asking Notion for its comments each time would be
  // polling a conversation that has not moved. The `reread` button is there.
  const moved = fresh.column !== state.ticket.column;
  state.ticket = fresh;
  drawTicketHead(fresh);
  if (moved) loadTalk(fresh);
}

function drawTicketHead(ticket) {
  $("ticket-title").textContent = ticket.title;
  const column = state.board.columns.find((item) => item.key === ticket.column)?.name
    || LABEL[ticket.column] || ticket.column;
  $("ticket-where").textContent = ticket.progress ? `${column} · ${ticket.progress}` : column;
  const links = $("ticket-links");
  links.textContent = "";
  links.append(link("Notion", ticket.url));
  if (ticket.pull_request) links.append(link("pull request", ticket.pull_request));
  if (ticket.session_link) links.append(link("session", ticket.session_link));
  $("ticket-state").textContent = ticket.short ? `#${ticket.short}` : "";
  $("ticket-input").disabled = false;
  $("ticket-send").disabled = false;
}

async function loadTalk(ticket) {
  const view = $("ticket-talk");
  let payload;
  try {
    payload = await api(`/api/tickets/${ticket.id}/talk`);
  } catch (error) {
    view.append(talkTurn({ role: "error", text: `could not read the discussion: ${error.message}` }));
    return scroll(view);
  }
  // Notion took a moment and you opened another card in it: this answer is
  // about a ticket nobody is looking at any more.
  if (!state.ticket || state.ticket.id !== ticket.id) return;
  // The steps of a running session are not part of the discussion and are not
  // reread with it — detached and put back, they keep scrolling underneath.
  const steps = state.ticketSteps;
  view.textContent = "";
  for (const message of payload.messages) view.append(talkTurn(message));
  if (!payload.messages.length)
    view.append(element("p", "empty", "Nothing has been said on this ticket yet."));
  if (steps) view.append(steps);
  $("ticket-hint").textContent =
    `a comment on the ticket · an answer to its question runs it again · `
    + `${payload.mention} asks it for words instead`;
  scroll(view);
}

function talkTurn(message) {
  const turn = element("div", `turn ${message.role}`);
  const who = message.role === "you" ? "you" : message.role === "error" ? "problem" : "the runner";
  const at = moment(message.at);
  turn.append(element("div", "who", at ? `${who} · ${at}` : who));
  turn.append(flow(element("div", "text"), message.text));
  return turn;
}

/** An instant as this browser would write it, or nothing at all. */
function moment(at) {
  if (!at) return "";
  const date = new Date(at);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
}

function ticketStep(event) {
  const view = $("ticket-talk");
  if (!state.ticketSteps || state.ticketSteps.parentNode !== view) {
    state.ticketSteps = element("div", "steps");
    view.append(state.ticketSteps);
  }
  state.ticketSteps.append(step(event));
  while (state.ticketSteps.childElementCount > 200) state.ticketSteps.firstElementChild.remove();
  state.ticketSteps.scrollTop = state.ticketSteps.scrollHeight;
  scroll(view);
}

/** Somebody wrote to a ticket — here, or in the other tab, or on a phone. */
function onTalk(event) {
  if (!state.ticket || event.ticket !== state.ticket.id) return;
  const view = $("ticket-talk");
  view.querySelector(".empty")?.remove();
  const steps = state.ticketSteps;
  view.append(talkTurn(event));
  if (steps && steps.parentNode === view) view.append(steps);
  scroll(view);
}

async function tell() {
  const field = $("ticket-input");
  const text = field.value.trim();
  if (!text || !state.ticket) return;
  const button = $("ticket-send");
  button.disabled = true;
  try {
    // Nothing is drawn here: what appears is what came back on the stream, so
    // the phone that sent it and the laptop that did not show the same thing.
    await api(`/api/tickets/${state.ticket.id}/talk`, { text });
    field.value = "";
    resizeTicket();
  } catch (error) {
    $("ticket-talk").append(talkTurn({ role: "error", text: `not written: ${error.message}` }));
    scroll($("ticket-talk"));
  } finally {
    button.disabled = false;
  }
}

function resizeTicket() {
  const field = $("ticket-input");
  field.style.height = "auto";
  field.style.height = `${Math.min(field.scrollHeight, 200)}px`;
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
  if (info.update) add(`${info.update} available · run update`, "warn");
  const version = $("version");
  version.textContent = info.version ? `v${info.version}` : "";
  version.title = info.update
    ? `v${info.version} — ${info.update} is waiting, run: ticket-runner update`
    : `v${info.version} — the version this console is running`;
  $("chat-state").textContent = info.chat.session_id
    ? `${info.chat.turns} turn(s) · ${info.chat.resume_command}`
    : "no conversation yet";
}

function every(seconds) {
  if (!seconds) return "";
  return seconds < 120 ? `${seconds}s` : `${Math.round(seconds / 60)} min`;
}

/* -- settings ---------------------------------------------------------------
 *
 * Drawn from what the server says the configuration holds, never from a list
 * kept here: a setting the runner gains appears in this tab the day it is
 * described, and one it loses stops being offered.
 *
 * A field carries three states, not two — what the file says, what the runner
 * falls back on when it says nothing, and what you have just typed. Clearing a
 * field is how you go back to the third, and it removes the line rather than
 * writing an empty one.
 */

// The command each section is checked with. The CLI already knows how to say
// whether a token works; the settings tab does not need a second opinion.
const CHECKS = {
  notion: ["doctor", "does that token reach your board?"],
  notify: ["notify", "send yourself a test message"],
  runner: ["enable", "apply the interval to the timer"],
};

async function loadSettings() {
  try {
    const payload = await api("/api/settings");
    state.settings.drawn = payload;
    state.settings.edited.clear();
    state.settings.projects = null;
    renderSettings();
  } catch (error) {
    say("error", `could not read the configuration: ${error.message}`);
  }
}

function renderSettings() {
  const payload = state.settings.drawn;
  if (!payload) return;
  $("settings-path").textContent = payload.path;
  const problem = $("settings-problem");
  problem.textContent = payload.problem || "";
  problem.hidden = !payload.problem;

  const host = $("settings-sections");
  host.textContent = "";
  // Open where somebody arriving would start, folded where they would not:
  // seventy fields at once is a file, not a page.
  const open = new Set(["notion", "runner", "notify"]);
  for (const section of payload.sections) {
    const box = element("details", "group");
    box.open = open.has(section.key);
    const head = element("summary");
    head.append(element("span", "group-title", section.title));
    const check = CHECKS[section.key];
    if (check) {
      const button = action(`> ${check[0]}`, (event) => {
        event.preventDefault();
        runCheck(check[0]);
      });
      button.title = check[1];
      button.className = "check-run";
      head.append(button);
    }
    box.append(head);
    box.append(rich(element("p", "blurb"), section.blurb));
    if (section.pairs === "projects") box.append(projectRows(payload.projects));
    else {
      const grid = element("div", "fields");
      for (const field of section.fields) grid.append(fieldRow(field));
      box.append(grid);
    }
    host.append(box);
  }
  showSaveBar();
}

function fieldRow(field) {
  const row = element("div", `field ${field.kind}`);
  // A <label> around its own control, except where the control is itself a row
  // of labels: nesting one label in another is invalid, and the browser pulls
  // the inner ones apart to say so.
  const wrap = element(field.kind === "events" ? "div" : "label", "stack");
  wrap.append(element("span", "name", field.label));
  wrap.append(fieldControl(field));
  row.append(wrap);
  if (field.help) row.append(rich(element("p", "help"), field.help));
  if (field.after) row.append(rich(element("p", "after"), `takes effect once ${field.after}`));
  return row;
}

function fieldControl(field) {
  const remember = (value) => {
    if (same(value, initial)) state.settings.edited.delete(field.name);
    else state.settings.edited.set(field.name, value);
    showSaveBar();
  };
  let initial = field.value;

  if (field.kind === "bool") {
    // Three answers, because the file has three: yes, no, and nothing — which
    // is the runner's own default and says so.
    const select = element("select");
    select.append(option("", `default · ${field.fallback ? "yes" : "no"}`));
    select.append(option("true", "yes"), option("false", "no"));
    select.value = field.value === null ? "" : String(field.value);
    initial = field.value;
    select.addEventListener("change", () =>
      remember(select.value === "" ? null : select.value === "true"));
    return select;
  }

  if (field.kind === "choice") {
    const select = element("select");
    select.append(option("", `default · ${field.fallback}`));
    for (const choice of field.choices) select.append(option(choice, choice));
    select.value = field.value || "";
    initial = field.value || "";
    select.addEventListener("change", () => remember(select.value || null));
    return select;
  }

  if (field.kind === "events") {
    const box = element("div", "events");
    const chosen = new Set(field.value === null ? field.fallback : field.value);
    initial = field.value;
    for (const choice of field.choices) {
      const tick = element("label", "check");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = chosen.has(choice);
      input.addEventListener("change", () => {
        if (input.checked) chosen.add(choice);
        else chosen.delete(choice);
        remember(field.choices.filter((name) => chosen.has(name)));
      });
      tick.append(input, textNode(choice));
      box.append(tick);
    }
    return box;
  }

  if (field.kind === "secret") {
    const box = element("div", "secret");
    const input = document.createElement("input");
    input.type = "password";
    input.autocomplete = "off";
    input.spellcheck = false;
    input.placeholder = field.preview ? `set · ends ${field.preview}` : "not set";
    initial = "";
    input.addEventListener("input", () => remember(input.value.trim() || ""));
    box.append(input);
    if (field.preview) {
      // Emptying the box means "I did not retype it", so forgetting a token has
      // to be a gesture of its own rather than the absence of one.
      const forget = action("forget", () => {
        input.value = "";
        input.placeholder = "not set";
        state.settings.edited.set(field.name, null);
        forget.disabled = true;
        showSaveBar();
      });
      box.append(forget);
    }
    return box;
  }

  const input = document.createElement("input");
  input.type = field.kind === "int" ? "number" : "text";
  input.autocomplete = "off";
  input.spellcheck = false;
  input.value = field.value === null ? "" : String(field.value);
  input.placeholder = field.fallback === "" || field.fallback === null
    ? "nothing"
    : `default · ${field.fallback}`;
  input.addEventListener("input", () => {
    const text = input.value.trim();
    if (field.kind === "int") remember(text === "" ? null : Number(text));
    else remember(text);
  });
  return input;
}

function projectRows(projects) {
  const box = element("div", "pairs");
  const rows = state.settings.projects || projects.map((item) => ({ ...item }));
  const changed = () => {
    state.settings.projects = rows;
    showSaveBar();
  };
  const draw = () => {
    box.textContent = "";
    rows.forEach((row, index) => {
      const line = element("div", "pair");
      const name = document.createElement("input");
      name.value = row.name;
      name.placeholder = "the project, as Notion names it";
      name.addEventListener("input", () => { row.name = name.value; changed(); });
      const path = document.createElement("input");
      path.value = row.path;
      path.placeholder = "~/workspace/that-repository";
      path.addEventListener("input", () => { row.path = path.value; changed(); });
      line.append(name, path, action("remove", () => { rows.splice(index, 1); changed(); draw(); }));
      box.append(line);
    });
    if (!rows.length) box.append(element("p", "empty", "No mapping here — the project pages carry it."));
    box.append(action("add a project", () => { rows.push({ name: "", path: "" }); changed(); draw(); }));
  };
  draw();
  return box;
}

function showSaveBar() {
  const count = state.settings.edited.size + (state.settings.projects ? 1 : 0);
  $("savebar").hidden = !count;
  $("savebar-text").textContent = count === 1 ? "one change, unsaved" : `${count} changes, unsaved`;
}

async function saveSettings() {
  const payload = { settings: Object.fromEntries(state.settings.edited) };
  if (state.settings.projects) payload.projects = state.settings.projects;
  $("settings-save").disabled = true;
  try {
    const result = await api("/api/settings", payload);
    await loadSettings();
    await refreshState();
    const saved = result.saved.length;
    note(saved
      ? `Saved ${saved === 1 ? "one setting" : `${saved} settings`}: ${result.saved.join(", ")}.`
        + (result.after.length ? ` Takes effect once ${result.after.join("; ")}.` : "")
      : "Nothing to save — the file already said that.");
  } catch (error) {
    // On the settings tab, not in the transcript: on a phone the console is a
    // tab away, and a save you have to go looking for is a save you doubt.
    note(`Not saved: ${error.message}`, true);
  } finally {
    $("settings-save").disabled = false;
  }
}

let noteTimer = 0;

/** What became of the last save, where the last save happened. */
function note(text, bad = false) {
  const node = $("settings-note");
  node.textContent = "";
  rich(node, text);
  node.className = `notice ${bad ? "bad" : "good"}`;
  node.hidden = false;
  clearTimeout(noteTimer);
  // A problem stays until it is read; a confirmation has been read by then.
  if (!bad) noteTimer = setTimeout(() => { node.hidden = true; }, 8000);
}

function runCheck(verb) {
  show("console");
  api("/api/command", { line: verb }).catch((error) => say("error", error.message));
}

function option(value, label) {
  const node = element("option", null, label);
  node.value = value;
  return node;
}

function same(left, right) {
  if (Array.isArray(left) && Array.isArray(right))
    return left.length === right.length && left.every((item, index) => item === right[index]);
  return left === right;
}

/* An address in a line of text becomes a link, and nothing else does.
 *
 * Answers, command output and the steps of a session all carry them — a pull
 * request, a Notion page, a preview — and reading one out loud into another tab
 * is not a gesture anybody should have to make. The rule at the top of this file
 * holds: the address lands in an anchor's `textContent`, never in markup. */
const ADDRESS = /https?:\/\/[^\s<>"'`]+/g;

function flow(node, text) {
  const line = String(text);
  let last = 0;
  for (const found of line.matchAll(ADDRESS)) {
    const address = trimmed(found[0]);
    node.append(textNode(line.slice(last, found.index)), link(address, address));
    last = found.index + address.length;
  }
  node.append(textNode(line.slice(last)));
  return node;
}

/** A URL without the punctuation that ended the sentence it was written in. */
function trimmed(address) {
  let end = address.length;
  while (end > 0) {
    const last = address[end - 1];
    if (".,;:!?".includes(last)) end -= 1;
    // A closing bracket is part of the address only where the address opened
    // one: an encyclopaedia writes them, a sentence in parentheses does not.
    else if ((last === ")" && !address.slice(0, end).includes("(")) ||
             (last === "]" && !address.slice(0, end).includes("["))) end -= 1;
    else break;
  }
  return address.slice(0, end);
}

/** Backticked words become <code>, and nothing else becomes markup. */
function rich(node, text) {
  text.split("`").forEach((part, index) => {
    node.append(index % 2 ? element("code", null, part) : textNode(part));
  });
  return node;
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
  $("ticket-input").addEventListener("input", resizeTicket);
  $("ticket-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      tell();
    }
  });
  $("ticket-send").addEventListener("click", tell);
  $("ticket-reread").addEventListener("click", () => { if (state.ticket) loadTalk(state.ticket); });

  $("refresh").addEventListener("click", () => api("/api/refresh", {}).catch(() => {}));
  $("settings-save").addEventListener("click", saveSettings);
  $("settings-revert").addEventListener("click", loadSettings);

  $("new-title").addEventListener("focus", () => { $("compose-more").hidden = false; });
  $("new-title").addEventListener("keydown", (event) => {
    if (event.key === "Enter") create();
  });
  $("create").addEventListener("click", create);

  // The stream first, and only then the three reads: two of them ask Notion,
  // and a console that opened its live connection *after* a slow board sat
  // there saying "connecting…" for as long as Notion took to answer.
  connect();
  await refreshState();
  await loadChat();
  await loadProjects();
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
  // Read the first time the tab is opened rather than at boot: most sessions
  // never open it, and the board is what people came for.
  if (pane === "settings" && !state.settings.drawn) loadSettings();
  document.querySelectorAll(".tabs button").forEach((button) => {
    button.classList.toggle("on", button.dataset.pane === pane);
  });
  for (const name of ["board", "ticket", "console", "live", "settings"]) {
    $(`pane-${name}`).classList.toggle("showing", name === pane);
  }
  // On a wide screen the console is always the right-hand column, whichever of
  // the other two is chosen — so choosing one must not take it away.
  if (window.matchMedia("(min-width: 861px)").matches) {
    $("pane-console").classList.add("showing");
  }
}

boot();
