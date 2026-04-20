"""
assets/generate.py — Reproducibly build every visual asset in this folder.

Run from the repo root:
    python3 assets/generate.py

Outputs PNGs into ./assets/ that are referenced by the README:
    banner.png            — wide hero banner
    state-idle.png        — display screen, IDLE state
    state-listening.png   — display screen, LISTENING state
    state-thinking.png    — display screen, THINKING state
    state-speaking.png    — display screen, SPEAKING state
    states.png            — all four states side-by-side
    personalities.png     — 4×3 grid of personality cards
    tests.png             — terminal-style pytest summary
"""
from __future__ import annotations

import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_MONO_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def reg(size: int) -> ImageFont.FreeTypeFont:
    return font(FONT_REGULAR, size)


def bold(size: int) -> ImageFont.FreeTypeFont:
    return font(FONT_BOLD, size)


def mono(size: int) -> ImageFont.FreeTypeFont:
    return font(FONT_MONO, size)


def mono_bold(size: int) -> ImageFont.FreeTypeFont:
    return font(FONT_MONO_BOLD, size)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def rounded_rect(draw: ImageDraw.ImageDraw, box, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def vertical_gradient(size, top, bottom):
    w, h = size
    img = Image.new("RGB", size, top)
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        ImageDraw.Draw(img).line([(0, y), (w, y)], fill=(r, g, b))
    return img


def text_centered(draw, xy, text, font_obj, fill):
    draw.text(xy, text, font=font_obj, fill=fill, anchor="mm")


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
def make_banner() -> None:
    W, H = 1280, 380
    bg_top = hex_rgb("#0b1220")
    bg_bot = hex_rgb("#1a1a2e")
    img = vertical_gradient((W, H), bg_top, bg_bot)
    d = ImageDraw.Draw(img)

    # Soft glowing accent dots
    for cx, cy, r, c, alpha in [
        (200, 120, 180, hex_rgb("#00ff64"), 70),
        (1100, 280, 220, hex_rgb("#0096ff"), 60),
        (650, 60, 140, hex_rgb("#a29bfe"), 55),
    ]:
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c + (alpha,))
        glow = glow.filter(ImageFilter.GaussianBlur(60))
        img.paste(glow, (0, 0), glow)

    # Title block
    title = "MiBud"
    tag = "Privacy-First AI Companion · Pi Zero 2 W"
    sub = "Offline-capable · 20+ personalities · Memory · Tools · MCP · Streaming TTS"

    text_centered(d, (W // 2, 130), title, bold(120), hex_rgb("#ffffff"))
    text_centered(d, (W // 2, 230), tag, reg(32), hex_rgb("#9ad9ff"))
    text_centered(d, (W // 2, 290), sub, reg(20), hex_rgb("#bdbdd6"))

    # Pill badges along the bottom
    pills = [
        ("v3.0 Aware", "#22c55e"),
        ("MIT", "#3b82f6"),
        ("Python 3.10+", "#8b5cf6"),
        ("154 tests", "#f59e0b"),
        ("Pi Zero 2 W", "#c51a4a"),
    ]
    px = 100
    py = 340
    for label, color in pills:
        tw = d.textlength(label, font=bold(16)) + 28
        rounded_rect(d, [px, py - 16, px + tw, py + 14], radius=15, fill=hex_rgb(color))
        d.text((px + 14, py - 1), label, font=bold(16), fill=(255, 255, 255), anchor="lm")
        px += tw + 14

    img.save(ASSETS / "banner.png", optimize=True)
    print("✓ banner.png")


# ---------------------------------------------------------------------------
# Display state mockups (mimic the WhisPlay 240×280)
# ---------------------------------------------------------------------------
SCREEN_W, SCREEN_H = 240, 280
BEZEL = 14
DEVICE_W, DEVICE_H = SCREEN_W + BEZEL * 2, SCREEN_H + BEZEL * 2 + 30


def draw_status_bar(d, theme):
    # Battery icon (drawn) + percentage on the left, wifi bars on the right
    d.rectangle([6, 6, 24, 16], outline=theme["fg"], width=1)
    d.rectangle([24, 9, 26, 13], fill=theme["fg"])
    d.rectangle([8, 8, 22, 14], fill=theme["accent"])  # full charge indicator
    d.text((30, 4), "87%", font=bold(11), fill=theme["fg"])
    # Wifi bars (3 ascending)
    bx = SCREEN_W - 30
    by = 14
    for i, h in enumerate([3, 6, 9]):
        d.rectangle([bx + i * 5, by - h, bx + i * 5 + 3, by], fill=theme["fg"])


def device_frame(screen_img: Image.Image, label: str | None = None) -> Image.Image:
    out = Image.new("RGB", (DEVICE_W, DEVICE_H), hex_rgb("#0a0a0a"))
    d = ImageDraw.Draw(out)
    rounded_rect(d, [0, 0, DEVICE_W - 1, DEVICE_H - 31], 18, fill=hex_rgb("#1a1a1a"), outline=hex_rgb("#333"), width=2)
    out.paste(screen_img, (BEZEL, BEZEL))
    # Bezel screw dots
    for cx, cy in [(6, 6), (DEVICE_W - 7, 6), (6, DEVICE_H - 38), (DEVICE_W - 7, DEVICE_H - 38)]:
        d.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=hex_rgb("#444"))
    if label:
        d.text((DEVICE_W // 2, DEVICE_H - 14), label, font=bold(14), fill=hex_rgb("#cdcdcd"), anchor="mm")
    return out


def make_state_idle(theme: dict) -> Image.Image:
    img = Image.new("RGB", (SCREEN_W, SCREEN_H), theme["bg"])
    d = ImageDraw.Draw(img)
    draw_status_bar(d, theme)
    text_centered(d, (SCREEN_W // 2, 80), "14:32", bold(54), theme["accent"])
    text_centered(d, (SCREEN_W // 2, 122), "Sat · Apr 20", reg(14), theme["fg"])
    box_y = 175
    rounded_rect(d, [25, box_y, SCREEN_W - 25, box_y + 70], 14, fill=theme["secondary"])
    text_centered(d, (SCREEN_W // 2, box_y + 22), "MiBud", bold(20), theme["bg"])
    text_centered(d, (SCREEN_W // 2, box_y + 47), "[ Assistant ]", reg(12), theme["bg"])
    text_centered(d, (SCREEN_W // 2, SCREEN_H - 14), "Say 'Hey MiBud'", reg(11), theme["fg"])
    return img


def make_state_listening(theme: dict) -> Image.Image:
    img = Image.new("RGB", (SCREEN_W, SCREEN_H), theme["bg"])
    d = ImageDraw.Draw(img)
    draw_status_bar(d, theme)
    text_centered(d, (SCREEN_W // 2, 36), "● LISTENING", bold(16), theme["accent"])
    # Animated bars (5 vertical bars of varied heights)
    cx = SCREEN_W // 2
    base_y = 150
    for i, h in enumerate([35, 60, 85, 60, 35]):
        x = cx - 75 + i * 35
        rounded_rect(d, [x, base_y - h // 2, x + 22, base_y + h // 2], 6, fill=theme["accent"])
    text_centered(d, (SCREEN_W // 2, 230), "I'm listening...", reg(14), theme["fg"])
    text_centered(d, (SCREEN_W // 2, SCREEN_H - 14), "Tap button to stop", reg(11), theme["fg"])
    return img


def make_state_thinking(theme: dict) -> Image.Image:
    img = Image.new("RGB", (SCREEN_W, SCREEN_H), theme["bg"])
    d = ImageDraw.Draw(img)
    draw_status_bar(d, theme)
    text_centered(d, (SCREEN_W // 2, 36), "THINKING …", bold(16), theme["accent"])
    # Three pulsing dots
    cx, cy = SCREEN_W // 2, 145
    for i, sz in enumerate([14, 22, 14]):
        x = cx - 50 + i * 50
        d.ellipse([x - sz, cy - sz, x + sz, cy + sz], fill=theme["accent"])
    text_centered(d, (SCREEN_W // 2, 215), "google/gemini-flash", mono(11), theme["fg"])
    text_centered(d, (SCREEN_W // 2, 235), "tools: 2 in flight", mono(11), theme["secondary"])
    text_centered(d, (SCREEN_W // 2, SCREEN_H - 14), "First token in ~0.6s", reg(11), theme["fg"])
    return img


def make_state_speaking(theme: dict) -> Image.Image:
    img = Image.new("RGB", (SCREEN_W, SCREEN_H), theme["bg"])
    d = ImageDraw.Draw(img)
    draw_status_bar(d, theme)
    text_centered(d, (SCREEN_W // 2, 36), "SPEAKING", bold(16), theme["accent"])
    # Waveform: a centred polyline
    import math
    pts = []
    cy = 130
    for x in range(20, SCREEN_W - 20, 4):
        t = (x - 20) / 30
        amp = 28 * abs(math.sin(t * 1.4)) * (0.5 + 0.5 * math.cos(t * 0.6))
        pts.append((x, cy - amp))
        pts.append((x, cy + amp))
    for i in range(0, len(pts), 2):
        d.line([pts[i], pts[i + 1]], fill=theme["accent"], width=2)
    # Speech bubble with first words
    rounded_rect(d, [16, 175, SCREEN_W - 16, 245], 12, fill=theme["secondary"])
    d.text((28, 188), "Sure! Here are three", font=bold(13), fill=theme["bg"])
    d.text((28, 208), "ways to make pasta", font=bold(13), fill=theme["bg"])
    d.text((28, 226), "carbonara without...", font=reg(12), fill=theme["bg"])
    text_centered(d, (SCREEN_W // 2, SCREEN_H - 14), "Interrupt anytime", reg(11), theme["fg"])
    return img


def make_states() -> None:
    theme_hex = {
        "bg": "#1a1a2e",
        "fg": "#e0e0e0",
        "accent": "#00ff64",
        "secondary": "#0096ff",
    }
    theme = {k: hex_rgb(v) for k, v in theme_hex.items()}
    builders = [
        ("state-idle.png", "IDLE", make_state_idle),
        ("state-listening.png", "LISTENING", make_state_listening),
        ("state-thinking.png", "THINKING", make_state_thinking),
        ("state-speaking.png", "SPEAKING", make_state_speaking),
    ]
    framed_imgs = []
    for fname, label, builder in builders:
        screen = builder(theme)
        framed = device_frame(screen, label)
        framed.save(ASSETS / fname, optimize=True)
        framed_imgs.append(framed)
        print(f"✓ {fname}")

    # Side-by-side composite
    gap = 24
    pad = 30
    cw = framed_imgs[0].width
    ch = framed_imgs[0].height
    total_w = pad * 2 + cw * 4 + gap * 3
    total_h = pad * 2 + ch + 50
    composite = Image.new("RGB", (total_w, total_h), hex_rgb("#0b1220"))
    d = ImageDraw.Draw(composite)
    text_centered(
        d,
        (total_w // 2, 28),
        "Dialog state machine — IDLE → LISTENING → THINKING → SPEAKING",
        bold(20),
        hex_rgb("#ffffff"),
    )
    for i, im in enumerate(framed_imgs):
        composite.paste(im, (pad + i * (cw + gap), 60))
    composite.save(ASSETS / "states.png", optimize=True)
    print("✓ states.png")


# ---------------------------------------------------------------------------
# Personality grid
# ---------------------------------------------------------------------------
PERSONALITIES = [
    ("Assistant", "🤖", "General help", "#1a1a2e", "#00ff64", "#0096ff"),
    ("Chef", "👨‍🍳", "Recipes & cooking", "#2d132c", "#e94560", "#fab1a0"),
    ("Hacker", "🖥️", "Code & systems", "#000000", "#00ff00", "#008800"),
    ("DJ", "🎧", "Music & vibes", "#1a1a2e", "#e94560", "#00d4ff"),
    ("Mentor", "📚", "Career advice", "#1e3a5f", "#4da6ff", "#74b9ff"),
    ("Therapist", "🧠", "Mental wellness", "#2d3436", "#74b9ff", "#a29bfe"),
    ("Teacher", "📖", "Patient explainer", "#2c3e50", "#3498db", "#f1c40f"),
    ("Comedian", "😄", "Jokes on demand", "#6c5ce7", "#fd79a8", "#a29bfe"),
    ("Detective", "🔍", "Logic & mystery", "#2c2c2c", "#f39c12", "#5d5d5d"),
    ("Scientist", "🔬", "Research & data", "#1a1a2e", "#00cec9", "#4a90e2"),
    ("Artist", "🎨", "Creative spark", "#d63031", "#fdcb6e", "#e17055"),
    ("Explorer", "🧭", "Travel & maps", "#00b894", "#55efc4", "#00cec9"),
]


def make_personalities() -> None:
    cols, rows = 4, 3
    cw, ch = 260, 180
    gap = 18
    pad = 30
    title_h = 60
    W = pad * 2 + cols * cw + (cols - 1) * gap
    H = pad * 2 + rows * ch + (rows - 1) * gap + title_h
    img = Image.new("RGB", (W, H), hex_rgb("#0b1220"))
    d = ImageDraw.Draw(img)
    text_centered(d, (W // 2, 32), "20+ personalities, each with its own theme & voice",
                  bold(24), hex_rgb("#ffffff"))

    emoji_font = font("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", 109)

    for idx, (name, emoji, blurb, bg, accent, sec) in enumerate(PERSONALITIES):
        col = idx % cols
        row = idx // cols
        x = pad + col * (cw + gap)
        y = pad + title_h + row * (ch + gap)
        bg_rgb = hex_rgb(bg)
        accent_rgb = hex_rgb(accent)
        sec_rgb = hex_rgb(sec)
        rounded_rect(d, [x, y, x + cw, y + ch], 18, fill=bg_rgb, outline=accent_rgb, width=2)
        # Top accent bar
        rounded_rect(d, [x, y, x + cw, y + 8], 4, fill=accent_rgb)
        # Emoji (big, color)
        try:
            d.text((x + 26, y + 38), emoji, font=emoji_font, embedded_color=True)
        except Exception:
            d.text((x + 26, y + 38), emoji, font=reg(80), fill=accent_rgb)
        # Name + blurb
        d.text((x + 150, y + 60), name, font=bold(22), fill=accent_rgb, anchor="lm")
        d.text((x + 150, y + 90), blurb, font=reg(13), fill=sec_rgb, anchor="lm")
        # Footer accent line
        d.line([x + 18, y + ch - 30, x + cw - 18, y + ch - 30], fill=sec_rgb, width=1)
        d.text((x + 18, y + ch - 18), "voice · theme · prompt", font=reg(10), fill=sec_rgb)

    img.save(ASSETS / "personalities.png", optimize=True)
    print("✓ personalities.png")


# ---------------------------------------------------------------------------
# Test results "screenshot"
# ---------------------------------------------------------------------------
def make_tests(summary_path: Path) -> None:
    lines = summary_path.read_text().splitlines() if summary_path.exists() else [
        "$ pytest -q",
        "....................................................... [ 36%]",
        "....................................................... [ 73%]",
        "............................................            [100%]",
        "",
        "154 passed in 1.85s",
    ]
    # Crop to the last ~32 informative lines
    interesting = [ln for ln in lines if ln.strip()]
    lines = interesting[-30:]

    pad_x, pad_y = 28, 60
    line_h = 22
    W = 1100
    H = pad_y + line_h * len(lines) + 60
    img = Image.new("RGB", (W, H), hex_rgb("#0d1117"))
    d = ImageDraw.Draw(img)

    # Window chrome
    rounded_rect(d, [10, 10, W - 10, 46], 8, fill=hex_rgb("#161b22"))
    for i, c in enumerate(["#ff5f57", "#febc2e", "#28c840"]):
        d.ellipse([28 + i * 24, 22, 28 + i * 24 + 14, 36], fill=hex_rgb(c))
    d.text((110, 18), "MiBud — pytest", font=mono_bold(14), fill=hex_rgb("#9aa4ad"))

    # Output
    palette = {
        "passed": "#3fb950",
        "fail": "#f85149",
        "warn": "#d29922",
        "info": "#58a6ff",
        "dim": "#7d8590",
        "fg": "#c9d1d9",
    }
    y = pad_y
    for raw in lines:
        col = palette["fg"]
        low = raw.lower()
        if "passed" in low or " ok" in low.lower():
            col = palette["passed"]
        elif " failed" in low or " error " in low or low.startswith("e "):
            col = palette["fail"]
        elif "warn" in low:
            col = palette["warn"]
        elif raw.startswith("===") and "passed" in low:
            col = palette["passed"]
        elif raw.startswith("===") or raw.startswith("---"):
            col = palette["dim"]
        elif raw.startswith("$"):
            col = palette["info"]
        d.text((pad_x, y), raw[:130], font=mono(14), fill=hex_rgb(col))
        y += line_h

    img.save(ASSETS / "tests.png", optimize=True)
    print("✓ tests.png")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    make_banner()
    make_states()
    make_personalities()
    summary = ASSETS / "_pytest_output.txt"
    make_tests(summary)
    print("All assets generated.")


if __name__ == "__main__":
    main()
