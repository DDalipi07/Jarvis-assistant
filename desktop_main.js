/*
 * JARVIS desktop app.
 * Opens Jarvis in its own window and shows Instagram live inside the Instagram panel.
 * Start it from the jarvis folder with:  npm start
 */
const { app, BrowserWindow, WebContentsView, ipcMain, session, shell } = require("electron");
const { spawn } = require("child_process");
const http = require("http");
const path = require("path");

const JARVIS_URL = "http://127.0.0.1:8000/jarvis_vision.html";
const JARVIS_ORIGIN = "http://127.0.0.1:8000";
let win = null, igView = null, server = null;

// Look like normal Chrome so sites (Instagram, Google sign-in) don't treat this as an unknown browser.
app.userAgentFallback = app.userAgentFallback.replace(/\s?Electron\/\S+/, "").replace(/\s?jarvis-desktop\/\S+/, "");

function serverUp() {
  return new Promise((resolve) => {
    const req = http.get(JARVIS_URL, (res) => { res.resume(); resolve(res.statusCode < 500); });
    req.on("error", () => resolve(false));
    req.setTimeout(1500, () => { req.destroy(); resolve(false); });
  });
}

async function ensureServer() {
  if (await serverUp()) return true;
  // Start the Jarvis server from this folder (python on Windows, python3 elsewhere).
  const py = process.platform === "win32" ? "python" : "python3";
  server = spawn(py, [path.join(__dirname, "jarvis_server.py")], { cwd: __dirname, stdio: "ignore", windowsHide: true });
  server.on("error", () => { server = null; });
  for (let i = 0; i < 30; i++) {
    await new Promise((r) => setTimeout(r, 500));
    if (await serverUp()) return true;
  }
  return false;
}

function createWindow() {
  win = new BrowserWindow({
    width: 1400, height: 900, minWidth: 900, minHeight: 600,
    backgroundColor: "#060c13", title: "Jarvis", autoHideMenuBar: true,
    webPreferences: { preload: path.join(__dirname, "desktop_preload.js"), contextIsolation: true, sandbox: true, nodeIntegration: false },
  });

  // Camera and microphone: allowed for the Jarvis page only.
  win.webContents.session.setPermissionRequestHandler((wc, permission, cb, details) => {
    const origin = (details && (details.requestingUrl || "")) || wc.getURL();
    cb(origin.startsWith(JARVIS_ORIGIN) && ["media", "notifications", "clipboard-sanitized-write", "fullscreen"].includes(permission));
  });

  // Pop-ups: Google sign-in opens inside the app; every other link opens in your normal browser.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("https://accounts.google.com/")) return { action: "allow", overrideBrowserWindowOptions: { width: 520, height: 700, autoHideMenuBar: true } };
    if (url.startsWith("https://www.instagram.com/")) { igGo(url); return { action: "deny" }; }
    if (/^https?:\/\//.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });
  // Keep the main window on Jarvis (Spotify login is allowed to come and go).
  win.webContents.on("will-navigate", (e, url) => {
    if (url.startsWith(JARVIS_ORIGIN) || url.startsWith("https://accounts.spotify.com/")) return;
    e.preventDefault(); if (/^https?:\/\//.test(url)) shell.openExternal(url);
  });

  // The live Instagram screen. It has its own saved login, separate from Jarvis.
  igView = new WebContentsView({ webPreferences: { partition: "persist:instagram", contextIsolation: true, sandbox: true } });
  igView.setBackgroundColor("#ffffff");
  win.contentView.addChildView(igView);
  setIgVisible(false);
  igView.webContents.loadURL("https://www.instagram.com/");
  igView.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("https://www.instagram.com/")) { igGo(url); return { action: "deny" }; }
    if (/^https?:\/\//.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });

  win.loadURL(JARVIS_URL);
  win.on("closed", () => { win = null; });
}

function setIgVisible(v) {
  if (!igView) return;
  if (typeof igView.setVisible === "function") igView.setVisible(v);
  if (!v) igView.setBounds({ x: 0, y: 0, width: 0, height: 0 });
}

function igGo(target) {
  if (!igView) return;
  const url = /^https:\/\/www\.instagram\.com\//.test(target) ? target : "https://www.instagram.com/" + String(target).replace(/^\/+/, "");
  igView.webContents.loadURL(url);
}

ipcMain.on("ig-rect", (e, r) => {
  if (!win || !igView || e.sender !== win.webContents) return;
  if (!r || !r.visible || r.width < 50 || r.height < 50) { setIgVisible(false); return; }
  const zoom = win.webContents.getZoomFactor();
  igView.setBounds({ x: Math.round(r.x * zoom), y: Math.round(r.y * zoom), width: Math.round(r.width * zoom), height: Math.round(r.height * zoom) });
  setIgVisible(true);
});
ipcMain.on("ig-go", (e, p) => { if (win && e.sender === win.webContents) igGo(p); });
ipcMain.on("ig-back", (e) => { if (win && e.sender === win.webContents && igView && igView.webContents.navigationHistory.canGoBack()) igView.webContents.navigationHistory.goBack(); });

app.whenReady().then(async () => {
  const ok = await ensureServer();
  createWindow();
  if (!ok) win.loadURL("data:text/html," + encodeURIComponent(
    "<body style='background:#060c13;color:#d6e6f1;font:16px sans-serif;padding:40px'><h2>Jarvis server didn't start</h2>" +
    "<p>Open CMD in your jarvis folder and run <b>python jarvis_server.py</b>, then restart this app.</p></body>"));
});
app.on("window-all-closed", () => { if (server) server.kill(); app.quit(); });
