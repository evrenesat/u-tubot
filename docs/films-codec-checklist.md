# Films spike: codec checklist for the TCL (issue 211)

Owner-run on the TV. The player plays whatever ExoPlayer's extractors and the TV's decoders handle; this list records what that is.

Setup: Settings, Updates, "Films developer entry" on, then "Films (developer)": stream addon address (Torrentio, Comet or MediaFusion, with
Real-Debrid configured in the addon; use `{token}` in the address and enter the token to keep it out of the stored address), an IMDb id, then "List
streams". Pick a stream per row of the table below (the stream name shows quality and codec). Optional: a skip list such as `30,90` to check a cut.

For each row write one line in the table below (copy it into a comment on the issue): plays / fails / plays without sound / no picture, the
decoder used (hardware name or software, from `adb logcat -s ExoPlayerImpl MediaCodecVideoRenderer` or the player's stats), and a note (stutter,
sync, wrong colours). Never paste an address or token.

| Case | Result | Decoder | Note |
|---|---|---|---|
| HEVC 4K (MKV) | | | |
| HDR10 | | | |
| Dolby Vision profile 5 | | | |
| Dolby Vision profile 7 | | | |
| Dolby Vision profile 8 | | | |
| AV1 | | | |
| Audio AC3 | | | |
| Audio E-AC3 | | | |
| Audio DTS | | | |
| Audio DTS-HD | | | |
| Audio TrueHD | | | |
| Subtitles SRT | | | |
| Subtitles ASS | | | |
| Subtitles PGS | | | |
| Skip list jumps over the range | | | |

The result decides: extend u·tubot (an FFmpeg audio extension for DTS/TrueHD) or fall back to the NuvioTV fork.
