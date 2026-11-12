# Installing u·tubot on a TV

u·tubot is an Android TV app (package `dev.utubot.tv`, it installs next to SmartTube or Electric Eel). The AI features need a
u·tubot backend that you or someone you trust runs: see [server.md](server.md). Without one the app still works as a
YouTube client, with no marks, summaries or HQ captions.

## 1. Pick the right APK

Every release has one APK per CPU architecture, named `u-tubot_<version>_<abi>.apk`:

| File | Use it on |
|---|---|
| `arm64-v8a` | most current Android TV boxes and TVs (64-bit ARM) |
| `armeabi-v7a` | older boxes, and devices with a 64-bit CPU but a 32-bit system (common on Fire TV sticks) |
| `x86` | emulators and x86 devices |
| `universal` | contains the ARM variants; works everywhere, larger download. Use it when unsure. |

To check a device over ADB: `adb shell getprop ro.product.cpu.abilist`. The first entry that exists as an APK is the right one.

Releases are on <https://github.com/evrenesat/u-tubot/releases> together with `SHA256SUMS`. The server operator can also
publish the same files on the server's own landing page (`https://utubot.example.com/`).

## 2. Install

**With Downloader (no PC needed).**

1. Install the free *Downloader* app (AFTVnews) on the TV from its store.
2. Open it and type the download code shown in the README or on your server's landing page. Or type the URL of a file instead:
   `https://utubot.example.com/app/latest/arm64-v8a.apk` (a stable link that always serves the newest release) or the GitHub
   release asset URL.
3. Allow Downloader to install unknown apps when Android asks, press Install, then Open.

**With ADB.** Enable developer options and network debugging on the TV, then:

```sh
adb connect TV_IP:5555
adb install u-tubot_0.2.1_arm64-v8a.apk
```

**With a USB stick** and any file manager app on the TV.

### Upgrading from 0.1.0

0.1.0 was an unpublished debug build signed with a different key. Android refuses to replace it, so uninstall it once before
installing 0.2.0 or later. From 0.2.0 on, updates install in place. If you ever see "App not installed" on an update, the
installed copy was signed by another key: uninstall and install again (app data is lost).

## 3. First run: Import setup and pair

1. A few seconds after launch the app offers **Import setup**. Pick *Not now* to be asked again next time or *Don't ask again*; you
   can always find it under *Settings, u·tubot, Import setup* (and *Pair with code* right below it).
2. Type your server's address, for example `utubot.example.com`. A bare host becomes `https://utubot.example.com/setup.json`.
   A full URL is fetched as typed. `http://` is accepted only for private addresses (LAN, loopback, tailnet, `.local`
   names, single-label names), so `10.0.0.20:8790` or `nas.local:8790` work for a server on your network.
3. The app stores the server address, the update address and the server's default switches, then opens the
   **6-digit pairing** dialog.
4. Get a code from the server operator (`utubot user pair NAME`, or the admin section of the web UI). Type it. The code is
   single use and valid for 15 minutes. The app receives its own device token; nothing else is typed on the TV.

Tip: some TV keyboards (for example TCL's T-IME) drop characters when text is sent in bulk with `adb shell input text`. Type
the address character by character (or paste it with the dialog's *Paste* button).

Pairing later or again: *Settings, u·tubot, Pair with code*. *Test connection* shows the server version and your user name.
*Advanced* holds the backend address and the token for manual setup.

Importing a setup from a different server replaces the stored address and drops the old token, so you pair again.

## 4. Updates

The app checks the update address from the imported setup (`<server>/app/update.json`) with Electric Eel's update checker:
*Settings, About, Updates* or the normal update prompt. It picks the file for the device's architecture. There is no built-in
update source: without an imported setup the app never checks for updates. Updates must be signed with the same key as the
installed app.

## 5. Using it

- Cards in rows get marks (clickbait, low quality, inflated length, unwanted topics) or are hidden, following the policy
  your server keeps for you: [policy.md](policy.md). *Mark only, never hide* keeps everything visible.
- Video menu (long press): **AI answer**, **Summary panel** on/off, **Prepare HQ captions**.
- Summary panel: with the panel switched on, focusing a card for about 0.7 seconds fills a side panel with that video's
  summary. Pick the prompt in the panel. See [prompt-sets.md](prompt-sets.md).
- HQ captions: after "Prepare HQ captions" finishes, the track "<language> (u·tubot)" appears in the subtitle picker, and is
  selected automatically unless you turn that off. See [captions.md](captions.md).
