// The glue between xterm.js and SlideMage (ui/workspace/terminal/web.py). Python owns the process: this page
// only draws what it is sent (base64 of the raw bytes), reports keystrokes, its size and selections, and
// takes colours from the app theme. Copy/paste: Ctrl+Shift+C / Ctrl+Shift+V (Cmd+C / Cmd+V on macOS).
"use strict";

let term = null;
let fit = null;
let bridge = null;

function bytesOf(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function applyTheme(json) {
  const theme = JSON.parse(json);
  document.body.style.background = theme.background;
  if (term) term.options.theme = theme;
}

let reported = { cols: 0, rows: 0 };

function refit() {
  if (!term || document.getElementById("term").clientWidth < 20) return;
  fit.fit();
  // Only a change of size is news: the process is resized (SIGWINCH) when it really is.
  if (term.cols === reported.cols && term.rows === reported.rows) return;
  reported = { cols: term.cols, rows: term.rows };
  bridge.page_resized(term.cols, term.rows);
}

function keyHandler(event) {
  if (event.type !== "keydown") return true;
  const key = event.key.toLowerCase();
  const mac = navigator.platform.toLowerCase().includes("mac");
  const copy = (event.ctrlKey && event.shiftKey && key === "c") || (mac && event.metaKey && key === "c")
    || (event.ctrlKey && key === "insert");
  const paste = (event.ctrlKey && event.shiftKey && key === "v") || (mac && event.metaKey && key === "v")
    || (event.shiftKey && key === "insert");
  if (copy && term.hasSelection()) { bridge.copy_text(term.getSelection()); return false; }
  if (paste) { bridge.paste_requested(); return false; }
  return true;
}

// The lines on the screen, each as [shown, with its dim cells as spaces], for terminal/draft.py: Claude Code's
// unsent prompt is the box's text that is not dim (its placeholder is).
function screenLines() {
  if (!term) return [];
  const buffer = term.buffer.active;
  const lines = [];
  for (let y = buffer.viewportY; y < buffer.viewportY + term.rows; y++) {
    const line = buffer.getLine(y);
    if (!line) continue;
    let shown = "", solid = "";
    for (let x = 0; x < term.cols; x++) {
      const cell = line.getCell(x);
      if (!cell || cell.getWidth() === 0) continue;
      const chars = cell.getChars() || " ";
      shown += chars;
      solid += cell.isDim() ? " ".repeat(chars.length) : chars;
    }
    lines.push([shown, solid]);
  }
  return lines;
}

function start() {
  term = new Terminal({
    fontFamily: '"Roboto Mono", monospace', fontSize: 12, lineHeight: 1.15, cursorBlink: true,
    scrollback: 5000, allowProposedApi: true, macOptionIsMeta: true,
    linkHandler: { activate: (_event, url) => bridge.open_url(url) },
  });
  fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open(document.getElementById("term"));
  term.attachCustomKeyEventHandler(keyHandler);
  term.onData((data) => bridge.send_input(data));
  term.onBinary((data) => bridge.send_binary(data));
  term.onSelectionChange(() => bridge.selection_changed(term.getSelection()));
  new ResizeObserver(refit).observe(document.getElementById("term"));

  bridge.output.connect((base64) => term.write(bytesOf(base64)));
  bridge.theme.connect(applyTheme);
  bridge.paste.connect((text) => term.paste(text));
  bridge.focus_terminal.connect(() => term.focus());
  bridge.reset_terminal.connect(() => term.reset());
  bridge.initial_theme((json) => {
    applyTheme(json);
    fit.fit();
    reported = { cols: term.cols, rows: term.rows };
    bridge.page_ready(term.cols, term.rows);
  });
}

new QWebChannel(qt.webChannelTransport, (channel) => {
  bridge = channel.objects.bridge;
  // Measuring the cells needs the font, so wait for it.
  Promise.race([document.fonts.load('12px "Roboto Mono"'), new Promise((r) => setTimeout(r, 1500))]).then(start);
});
