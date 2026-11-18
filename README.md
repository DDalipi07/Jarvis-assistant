# Jarvis: a personal AI assistant you control with your hands and voice

A desktop assistant that runs in your browser. It watches your webcam for hand gestures, talks back, sets alarms, reads you a daily news and stocks briefing, shows what's playing on Spotify, tracks your Google Classroom deadlines, and controls your computer's volume.

Bring your own AI: it works with a **Claude (Anthropic)** or **OpenAI** API key, and you choose the model.

> Fan project. Not affiliated with or endorsed by Marvel, Disney, Anthropic, OpenAI, Spotify or Google.

## Features

| | |
|---|---|
| ✋ **Hand gestures** | Webcam tracking (MediaPipe). Dismiss alarms, snooze, skip songs, start timers, read your schedule. Pinch and move to change volume. |
| 🗣️ **Voice** | Talk with the 🎤 button; Jarvis answers out loud with a British voice you can pick. |
| 🧠 **AI chat with web search** | Ask anything. Live answers for news, stocks and weather, with sources. |
| 📰 **Automatic briefing** | At 7:30 and 18:30: your stocks plus news on the topics you choose. |
| ⏰ **Alarms, reminders, timers** | Set them by typing, talking or gesturing. Wake up to beeps, your own audio file, or any Spotify song. |
| 🎓 **School** | Reads Google Classroom and school emails from Gmail, lists deadlines and reminds you the evening before and on the day. |
| 🎵 **Spotify** | Album cover pop-up for the current song; skip, pause or play by gesture or voice. |
| 📝 **Workspace (Google Docs & Slides)** | Write in Google Docs and Slides right inside Jarvis, or ask Jarvis to write a section of your essay or build a whole slide deck (with speaker notes) from one sentence. |
| 🌍 **Live dashboard** | A rotating holographic globe with continent labels and glowing network arcs, plus live charts for your stocks (Yahoo Finance, refreshed every minute). |
| 📺 **YouTube** | A YouTube screen inside Jarvis: search for videos, paste a link, or ask "play lo-fi study music" and Jarvis finds and plays it. An open palm pauses and resumes. |
| 📸 **Instagram** | One-click Feed, Reels, Messages and Explore in a window beside Jarvis, and paste any post or reel link to watch it inside Jarvis. |
| 📁 **Files** | Browse folders you choose (like your uni folder), search them, preview PDFs and images, and open files on your computer, or just ask Jarvis to find and open one. Read-only. |
| 📱 **Phone** | Alarms, reminders, new school tasks and the briefing pop up on your phone (free ntfy app), and alarms and reminders sync both ways with Google Calendar, so your phone alerts you even when the laptop is off. |
| 🔊 **Volume** | Change your computer's volume with a pinch gesture or by asking. |

## Requirements

- Windows or macOS
- Google Chrome or Microsoft Edge
- [Python 3.12](https://www.python.org/downloads/release/python-31210/) (tick **"Add Python to PATH"** when installing on Windows)
- A webcam (for gestures)
- An API key from [Anthropic](https://platform.claude.com/settings/keys) **or** [OpenAI](https://platform.openai.com/api-keys), with a little credit added

## Quick start

1. Download this repo: **Code → Download ZIP**, then unzip it.
2. Open the folder, click the address bar, type `cmd` and press Enter. (On a Mac, open Terminal and `cd` into the folder.)
3. Start Jarvis:
   ```
   python jarvis_server.py
   ```
4. In Chrome, open **http://127.0.0.1:8000/jarvis_vision.html**
5. In **Settings** (bottom right): choose **Claude** or **OpenAI**, pick a model, paste your API key and fill in your city, stocks and news topics.
6. Click **Activate camera** and show your hand.

Keep the command window open while you use Jarvis. Press **Ctrl + C** in it to stop.

## Choosing a model

| Provider | Model | Good for |
|---|---|---|
| Claude | Haiku 5.5 | Fastest and cheapest (a few cents a day) |
| Claude | Sonnet 5.5 | Smarter answers |
| Claude | Opus 5.5 | Most capable |
| OpenAI | GPT-6 Astra | Most capable |
| OpenAI | GPT-5.6 Terra | Faster and cheaper |

Pick **Other** to type any model name your account has access to. Web search is billed by your provider on top of normal usage.

## Gestures

Hold a gesture for one second.

| Gesture | Action |
|---|---|
| ✋ Open palm | Dismiss alarm, or pause/play music |
| 👍 Thumbs up | Snooze 5 min, or read what's next |
| 👎 Thumbs down | Next song |
| ✌️ Peace sign | Read your next 3 items |
| ☝️ Point up | Start a 5-minute timer |
| ✊ Fist | Mute or unmute Jarvis |
| 🤟 Rock on | Say hello |
| 👌 Pinch & move | Volume up or down |

## Optional setup

### Spotify
1. Go to the [Spotify developer dashboard](https://developer.spotify.com/dashboard) and click **Create app** (Spotify requires the app owner to have Premium).
2. Redirect URI: `http://127.0.0.1:8000/jarvis_vision.html`, then tick **Web API** and save.
3. Copy the **Client ID** into the **Now playing** panel and click **Connect**.

### School (Google Classroom + Gmail)
1. Turn on [2-Step Verification](https://myaccount.google.com/security) for your Gmail.
2. Create an [app password](https://myaccount.google.com/apppasswords) named "Jarvis".
3. In the **School** panel, enter your Gmail address, your school email (optional) and the app password.

If your school email is a separate Google account, forward it to your Gmail first: in the school Gmail, go to **Settings → Forwarding and POP/IMAP**.

### Google Docs & Slides (Workspace)
1. Go to the [Google Cloud console](https://console.cloud.google.com), create a project, and enable the **Google Docs API**, **Google Slides API** and **Google Drive API**.
2. Under **OAuth consent screen**, choose **External** and add yourself as a **Test user**.
3. Under **Credentials → Create credentials → OAuth client ID**, choose **Web application** and add `http://127.0.0.1:8000` as an authorized JavaScript origin.
4. Paste the **Client ID** into the **Workspace** panel and click **Connect Google**.

Jarvis only asks for access to Docs, Slides and the Drive files it creates or opens. AI-written text is a starting point; check it, and follow your university's rules on AI use.

### Phone (pop-ups and Google Calendar)
**Pop-ups:** install the free **ntfy** app on your phone ([iPhone](https://apps.apple.com/app/ntfy/id1625396347), [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy)). In Jarvis's **Phone** panel, tick the box, then subscribe to the topic it shows. Alarms, reminders, new school tasks and the briefing pop up on your phone with sound, even while you're using other apps. Keep the topic secret: anyone who knows it can read those pop-ups, and they pass through ntfy.sh.

**Google Calendar sync** (uses the Google Cloud project from the Workspace setup):
1. Enable the **Google Calendar API**.
2. Open **Credentials**, click your OAuth client, and add `http://127.0.0.1:8000/oauth/google` under **Authorized redirect URIs**.
3. Copy the **Client secret** and paste it, with the Client ID, into the **Phone** panel. Click **Connect Google**.
4. In **OAuth consent screen → Audience**, click **Publish app**. Otherwise Google signs Jarvis out every 7 days. Google will warn that the app isn't verified; it's your own app, so continue.

Alarms and reminders you set in Jarvis appear in your calendar with an alert, and timed events you add on your phone appear in Jarvis. The sign-in is encrypted on your computer and also powers Docs and Slides, so you no longer need to reconnect every hour.

### Phone app
A phone version of Jarvis lives in the `docs` folder and runs on GitHub Pages, free. It has chat with voice, your Google Calendar agenda (add alarms and reminders, and your phone alerts you for them), and the briefing. It installs like an app: open it in Safari or Chrome, then **Add to Home Screen**.

1. Fork this repo, then in your fork go to **Settings → Pages**, choose **Deploy from a branch**, pick **main** and **/docs**, and save. Your app will be at `https://<your-username>.github.io/<repo-name>/`.
2. In the laptop Jarvis, open the **Phone** panel, put that address in **Jarvis on your phone**, and click **Show QR code**. Scan it with your phone's camera: the app opens with your settings filled in. Tick **Include my API key** if you want the key copied too; the code then disappears after 90 seconds.
3. For the agenda, add the address shown in the app's **Settings → Google Calendar** to your OAuth client (Authorized JavaScript origins and redirect URIs).

The key and settings are stored only on your phone. The QR code's settings sit after the `#` in the link, which browsers never send to any server, and the app removes them from the address as soon as it reads them.

### Desktop app (Instagram live inside Jarvis)
Instagram blocks being shown inside web pages, so in Chrome it opens in a side window. To have it **live inside the Instagram panel**, run Jarvis as a desktop app:
1. Install [Node.js](https://nodejs.org) (the LTS version).
2. In the jarvis folder, run `npm install` once. If npm says Electron's install script was blocked, run `npm install-scripts approve electron` and then `npm install` again.
3. Start Jarvis with `npm start`. It starts the server for you.
4. **Desktop shortcut (Windows):** right-click **Start Jarvis.vbs** → **Show more options** → **Send to → Desktop (create shortcut)**. Then right-click the new shortcut → **Properties → Change Icon… → Browse**, pick `jarvis.ico` from the jarvis folder, and rename the shortcut to **Jarvis**. Double-click it to open Jarvis with no command window.

In the app, voice input (🎤) is off because it relies on Chrome's speech service. Everything else works.

### More voices
On Windows, open **Settings → Time & language → Speech → Add voices** and install **English (United Kingdom)**. Then pick a voice in the **Voice** menu under the chat.

## Privacy and security

- **Your API keys, Spotify login and preferences** are stored only in your browser on your computer (`localStorage`). They're sent only to the provider they belong to.
- **Your Gmail app password** is encrypted before it's saved: Windows encrypts it so only your Windows account can unlock it, and on macOS it goes into the Keychain. The settings file (`jarvis_config.json`) is listed in `.gitignore`, so it's never committed, and the server refuses to serve it to any web page.
- **The server only listens on `127.0.0.1`**, so other devices on your network can't reach it. It rejects requests from other websites (including DNS-rebinding tricks) and sends a strict security policy so the page can only talk to Anthropic, OpenAI, Spotify and the hand-tracking library.
- **Files:** Jarvis can only see folders you add in the Files panel, never changes or deletes anything, and won't run programs or scripts (they're only shown in Explorer). Previews need a secret that changes every time the server starts, so other websites can't read your files, and file names are never written to the log. File contents never leave your computer. The AI can't search your files unless you tick **Let the AI search these files** in the Files panel, and even then it only sees file names.
- **Only your computer can connect:** the server refuses any connection that doesn't come from this computer, and on Windows it locks its port so no other program can take it over.
- **Phone:** pop-ups go through ntfy.sh to the secret topic shown in the Phone panel. Calendar sync talks only to your own Google account.
- **Camera video** is processed in your browser and never uploaded.
- Calling AI APIs straight from the browser is fine for a personal app on your own computer. **Don't host this page on a public website with your key in it.**

## Files

| File | What it is |
|---|---|
| `jarvis_vision.html` | The app |
| `jarvis_server.py` | Small local server: serves the page, controls volume, reads school emails |
| `package.json`, `desktop_main.js`, `desktop_preload.js` | Optional desktop app (Electron) with Instagram docked inside |
| `Start Jarvis.vbs`, `jarvis.ico` | Double-click launcher for the desktop app (no command window) and its icon |
| `docs/` | The phone app (installable web app) |
| `jarvis_gestures.py` | Optional standalone Python gesture demo (`pip install mediapipe==0.10.21 "numpy<2" opencv-contrib-python==4.10.0.84`) |

## License

MIT. See [LICENSE](LICENSE).
