# SnapForge

Long website screenshots, scrolling videos, laptop and phone mockups, and a
rose growth reel for Instagram. Everything runs inside **Termux** on your
phone with one Python file: `shot.py`.

```
python shot.py
```

An animated mascot and a growing rose show the progress while it works.

---

## What it makes

| You pick | You get |
|---|---|
| Screenshot | One very long, sharp image of the whole page. Desktop mode and mobile mode. |
| Scrolling video | An MP4 of the page scrolling. The page's intro animation is filmed first. |
| Screenshot + video | Both of the above. |
| Mockup | The site inside a laptop and/or a phone frame, as a photo, a video, or both. |
| Rose reel | A 1080x1920 video of a rose growing, ready for Reels and Stories. |

---

## First-time setup

Open Termux, go to the folder where you saved `shot.py`, and run this once:

```
python shot.py --setup
```

This installs everything needed (Chromium, ffmpeg, Pillow, websocket-client)
and asks for storage permission so files can appear in your Gallery.

If setup fails to find Chromium, run these by hand, in this order:

```
pkg install -y x11-repo
pkg install -y tur-repo
pkg install -y python-pillow chromium ffmpeg
pip install websocket-client
termux-setup-storage
```

Pillow must come from `pkg`, not `pip`.

---

## Easy mode (menu)

```
python shot.py
```

It asks what you want to make, then only the questions that matter for that
choice. Press **Enter** at any question to take the default. After each job you
can paste another link.

## Command mode

```
python shot.py example.com                         # screenshots, desktop + mobile
python shot.py example.com -t video                # scrolling videos
python shot.py example.com -t both -m mobile       # screenshot + video, mobile only
python shot.py example.com -t mockup               # laptop + phone mockup photo
python shot.py example.com -t mockup --media video # page scrolls inside the mockup
python shot.py -t rose                             # rose reel (no link needed)
python shot.py --clean                             # free up storage
```

### Options

| Option | Meaning | Default |
|---|---|---|
| `-t`, `--type` | `shot`, `video`, `both`, `mockup`, `rose` | `shot` |
| `-m`, `--mode` | `desktop`, `mobile`, `both` | `both` |
| `-q`, `--quality` | `standard`, `high`, `ultra` | `high` |
| `-s`, `--speed` | Scroll speed: `slow` (150), `standard` (400), `fast` (800) or your own number in pixels per second | `standard` |
| `--pause`, `--intro` | Seconds to wait at the top before scrolling, so intro animations and loading screens play. `0` turns it off. | `4` |
| `-a`, `--anim` | Screenshots: `smart` scrolls section by section so animations play, `fast` takes an instant snapshot | `smart` |
| `-w`, `--wait` | Seconds to wait per section in smart screenshots (raise it for slow animations) | `1` |
| `--format` | Image format: `jpg` (much smaller) or `png` (sharpest, big files) | `jpg` |
| `--media` | Mockups: `photo`, `video`, `both` | `photo` |
| `--layout` | Mockups: `both` (laptop + phone), `laptop`, `phone`, `all` | `both` |
| `--theme` | Mockup background: `midnight`, `rose`, `ocean`, `light`, `greenscreen` | `midnight` |
| `--zoom` | Mockups at native pixels on a tight frame, sharp when you zoom or scale it later | off |
| `--rose-quality` | Rose reel: `fast` or `high` | `high` |
| `--rose-theme` | Rose reel background: `burgundy` or `greenscreen` | `burgundy` |
| `--clean` | Remove leftover temp files and caches, show storage used | |
| `--setup` | Install everything in Termux | |

---

## Where your files go

- `~/storage/shared/Pictures/WebShots`, which shows up in your **Gallery**
  as the *WebShots* album.
- If you never ran `termux-setup-storage`, files go to a `WebShots` folder in
  the folder you ran the script from, and the script tells you so.

File names look like `example.com_20261029_031952_mobile.jpg`.

---

## Quality levels

| Level | Videos | Best for |
|---|---|---|
| Standard | 1080p desktop, 780-wide phone, small files | Quick shares |
| High | 1080p desktop, 1080-wide phone | Most uses (recommended) |
| Ultra | 1620p desktop, 1170-wide phone, lossless frames | Maximum sharpness. Much slower, big files. |

Video colours are tagged correctly (BT.709), so they look the same on phones
and in editors.

---

## Screenshots: smart vs fast

- **Smart** (default) scrolls down one screen at a time and waits at each
  section, so scroll-triggered animations really play. Fixed bars (sticky
  headers) are shown once, not repeated.
- **Fast** takes the whole page in one go. Quicker, but animations that only
  start when scrolled into view may stay hidden.

---

## Scrolling videos

1. The page is loaded once and scrolled through to load everything.
2. It is reloaded and the **first seconds are filmed live** (`--pause`), so the
   loading screen and intro animation are in the video.
3. It scrolls down at a steady, even speed, one exact step per frame.
4. A short hold at the end.

Background `<video>` elements are paused and stepped forward in time with the
recording, so a background video plays at its true speed instead of racing.
Sites that use scroll-snap are handled too.

**Limits:** videos inside embeds (YouTube, Vimeo) and animations drawn by
JavaScript libraries can't be controlled, so they may still look a little off.

---

## Mockups

Laptop, phone, or both together, on a background you choose.

- **Photo** uses a clean first-screen capture after a fresh reload.
- **Video** scrolls the page inside the screens. With laptop and phone
  together, both scroll at the same time.
- **Green screen** theme: flat pure green (0, 255, 0), no shadows or glow, so
  you can key it out in your video editor. Photos are saved as PNG and videos
  use extra-clean settings.
- **Zoom-ready** (`--zoom`): each screen is drawn at exactly the pixels the
  browser captured, with no shrinking, on a frame that hugs the device. Use it
  when you will zoom in or scale the mockup in an editor. It makes bigger
  files and takes longer. Phone only is the fastest and sharpest.

Examples:

```
python shot.py example.com -t mockup --layout all --theme rose
python shot.py example.com -t mockup --media video --theme greenscreen --layout phone -q ultra --zoom
```

---

## Rose reel for Instagram

```
python shot.py -t rose
```

A 1080x1920 video (10 seconds on `high`, 7 on `fast`) of a rose growing with a
percentage under it, plus a PNG of the final bloom. Choose a burgundy or green
screen background. No website link needed.

---

## Saving storage

- Video frames go straight into ffmpeg. **Nothing temporary is written** to
  your phone's storage.
- Images default to JPG, which is roughly 5-8 times smaller than PNG.
- Old leftovers from crashed runs are removed automatically on start.
- The script refuses to start if less than 400 MB is free.
- `python shot.py --clean` clears leftovers and package caches and shows the
  size of your WebShots folder.

Delete old results in the Gallery (empty its trash too), or in Termux:

```
ls -lhS ~/storage/shared/Pictures/WebShots
rm ~/storage/shared/Pictures/WebShots/*.mp4
find ~/storage/shared/Pictures/WebShots -type f -mtime +7 -delete
```

`rm` and `find ... -delete` cannot be undone.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `Chromium not found` or `Pillow missing` | Run `python shot.py --setup` |
| `ffmpeg missing` | `pkg install ffmpeg` |
| `Could not open the page` | Check the link and your internet. Typos in the address are the usual cause. |
| Files not in the Gallery | Run `termux-setup-storage` once, then run the script again |
| Very long page, image looks softer | The script lowers sharpness on huge pages to protect your phone's memory |
| Animations missing in a screenshot | Use smart mode (default), or raise `-w` (for example `-w 2`) |
| Intro animation missing in a video | Raise `--pause` (for example `--pause 8`) |
| Terminal looks cut off or jumbled | Rotate the phone to landscape or reduce the Termux font size. The rose needs about 22 lines. |
| Video makes the phone slow or hot | Use `-q standard`, or a shorter page, or `--layout phone` for mockups |

Press **Ctrl+C** at any time to stop. The cursor and temp files are cleaned up.

---

## Good to know

- Only `http://` and `https://` links work. Pasted links are cleaned
  automatically (spaces, quotes, `<...>`, hidden characters).
- Pages behind a login or cookie banner are captured as a first-time visitor
  would see them.
- Pages taller than about 40,000 pixels are cut off at that height.
- Videos and mockups take noticeably longer than screenshots, and `ultra` takes
  the longest.
- Instagram recompresses uploads. Post the original file for the best result.
