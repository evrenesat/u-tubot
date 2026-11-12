<p align="center">
  <img src="assets/brand/utubot-symbol.svg" alt="u·tubot symbol" width="96" height="96">
</p>

<h1 align="center">u·tubot</h1>

> **Unofficial.** Not affiliated with Google or YouTube. Built on Electric Eel and SmartTube, which are separate projects; please don't report u·tubot issues to them.

u·tubot is an Android TV YouTube client with an AI layer you host yourself. A small backend asks the language model of your
choice (local or cloud, anything OpenAI-compatible) to mark or hide clickbait, low-quality and unwanted videos in your rows,
summarize or answer the video you are looking at, and build high-quality captions with Whisper. The TV app stays thin: it sends
video metadata and shows the results. Several people can share one server with their own policies.

## Download

Get the APK for your TV from [GitHub Releases](https://github.com/evrenesat/u-tubot/releases): `arm64-v8a` for most current
boxes, `armeabi-v7a` for older or 32-bit systems, `universal` when unsure. Each release lists the signing certificate and checksums.

**Downloader codes** (AFTVnews Downloader app: type the code, install):

| Build | Code |
|---|---|
| arm64-v8a | **3235617** |
| armeabi-v7a | **5947444** |

**Install:** install *Downloader* on the TV, enter the code (or a release URL), allow unknown sources when asked, install, open.
ADB and USB work too. Details and update notes: [docs/install.md](docs/install.md). Upgrading from the unpublished 0.1.0 debug
build needs one uninstall first.

## Features

- **Marks and hiding** on video cards: clickbait, low quality, inflated length (`12m≈2m`) and topics you do not want, with
  per-user thresholds. A mark-only mode never hides anything.
- **Summary panel**: focus a card and a small panel previews its summary; Info opens a Summary view with a prompt list and the long summary.
- **Your own prompts**: prompt sets are JSON files you host anywhere and import by URL; edit and test them in a web UI.
- **AI answer** to the question a title poses, from the video menu.
- **HQ captions** prepared in the background (yt-dlp, Whisper on CPU or a remote API, optional speaker labels).
- **Import setup**: type your server's address and the app configures itself, then pairs with a 6-digit code. No tokens on the TV.
- **Self-update** from your own server, checked automatically, one APK per CPU architecture.
- **Any LLM**: Ollama, llama.cpp, vLLM, LM Studio, OpenAI, OpenRouter or a router, mixed per task.

## Quick start

**TV:** install the APK, open *Settings, u·tubot, Import setup* (offered on first launch), type your server's address, then enter the
6-digit pairing code.

**Server:** Python 3.12, uv and ffmpeg.

```sh
cd ai-backend
uv sync
cp config.example.toml config.toml        # set providers, models, public_base_url
uv run utubot user add owner --admin
uv run utubot serve
uv run utubot user pair owner             # the code to type on the TV
```

Full guide with TLS, systemd and publishing APKs: [docs/server.md](docs/server.md).

## Screenshots

_Coming soon._

## Documentation

- [docs/install.md](docs/install.md): installing on a TV, Import setup, pairing, updates
- [docs/server.md](docs/server.md): running the backend, configuration reference, reverse proxy, publishing APKs
- [docs/llm-providers.md](docs/llm-providers.md): connecting language models
- [docs/prompt-sets.md](docs/prompt-sets.md): writing and importing prompts
- [docs/policy.md](docs/policy.md): marks, hiding, topics
- [docs/captions.md](docs/captions.md): HQ captions, ASR, speaker labels
- [docs/privacy.md](docs/privacy.md): what is sent and stored
- [docs/development.md](docs/development.md): building, testing, releasing, merging upstream
- [ai/CONTRACT.md](ai/CONTRACT.md): app/backend wire contract and the setup file
- [CHANGELOG.md](CHANGELOG.md)

## Credits

Based on [Electric Eel](https://github.com/cygnusx-1-org/electriceel) by cygnusx-1-org, itself based on
[SmartTube](https://github.com/yuliskov/SmartTube) by yuliskov. See their repositories for the features of the base app. They are
separate projects: report u·tubot problems in [this repository's issues](https://github.com/evrenesat/u-tubot/issues), not there.

## License

MIT, see [LICENSE](LICENSE). The original copyright notices of SmartTube and Electric Eel are kept.
