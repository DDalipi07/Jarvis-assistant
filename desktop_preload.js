// Bridge between the Jarvis page and the desktop app. Only these few functions are exposed.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("jarvisDesktop", {
  version: 1,
  // Where the Instagram screen should sit on the page (in page pixels), or hidden.
  instagramRect: (rect) => ipcRenderer.send("ig-rect", rect),
  // Open a part of Instagram in the docked screen: "", "reels/", "direct/inbox/", "explore/" or a full instagram.com link.
  instagramGo: (path) => ipcRenderer.send("ig-go", String(path || "")),
  instagramBack: () => ipcRenderer.send("ig-back"),
});
