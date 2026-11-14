"""Reproduce HomePanel's original scenic artwork. Requires the existing Pillow dependency."""
from pathlib import Path
import math
import random

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parents[1] / "web/wallpapers"
W, H = 1600, 1200


def sky(top, bottom):
    image = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(image)
    for y in range(H):
        t = (y / H) ** .8
        draw.line((0, y, W, y), fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bottom, strict=True)))
    return image


def ridge(image, points, color):
    ImageDraw.Draw(image).polygon([(0, H), *points, (W, H)], fill=color)


def haze(image, y, color, strength=45):
    layer = Image.new("RGBA", image.size)
    ImageDraw.Draw(layer).ellipse((-300, y - 100, W + 300, y + 100), fill=(*color, strength))
    return Image.alpha_composite(image.convert("RGBA"), layer.filter(ImageFilter.GaussianBlur(65))).convert("RGB")


def mountains():
    image = sky((25, 38, 58), (183, 153, 135))
    d = ImageDraw.Draw(image)
    d.ellipse((955, 230, 1045, 320), fill=(218, 204, 179))
    ridge(image, [(0, 720), (180, 570), (300, 610), (555, 310), (710, 490), (840, 420), (1100, 665), (1340, 430), (1600, 695)], "#71808c")
    d.polygon([(420, 470), (555, 310), (710, 490), (604, 434), (566, 397), (516, 440), (493, 424)], fill="#bac1bf")
    d.polygon([(1238, 539), (1340, 430), (1444, 537), (1376, 505), (1349, 483), (1314, 515)], fill="#adb9bb")
    image = haze(image, 680, (170, 179, 179), 75)
    ridge(image, [(0, 780), (210, 683), (420, 790), (650, 625), (890, 835), (1170, 730), (1400, 808), (1600, 714)], "#394f60")
    image = haze(image, 870, (102, 132, 145), 65)
    ridge(image, [(0, 882), (230, 922), (430, 868), (740, 1010), (1050, 894), (1350, 945), (1600, 842)], "#203846")
    return image


def forest():
    image = sky((30, 56, 61), (137, 167, 151))
    rng = random.Random(12)
    for count, base, size, color in [(85, 680, 140, "#668d84"), (65, 860, 230, "#395f58"), (28, 1180, 390, "#193d38")]:
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, base + 5, W, H), fill=color)
        for i in range(count):
            x = i * W / (count - 1) + rng.randrange(-35, 36)
            height = size * rng.uniform(.7, 1.4)
            bottom = base + rng.randrange(-45, 80)
            draw.rectangle((x - 2, bottom - height + 12, x + 2, bottom + 30), fill=color)
            for j in range(5):
                top = bottom - height + j * height * .13
                width = height * (.08 + j * .035)
                draw.polygon([(x, top), (x - width, top + height * .38), (x + width, top + height * .38)], fill=color)
        image = haze(image, base + 15, (176, 191, 170), 50 if base < 1000 else 15)
    return image


def coast():
    image = sky((48, 80, 103), (198, 205, 190))
    d = ImageDraw.Draw(image)
    d.rectangle((0, 520, W, H), fill="#537d8b")
    for i, color in enumerate(["#5b8994", "#62939c", "#6d9da3", "#7ca7a9", "#94b6b1"]):
        y = 560 + i * 95
        wave = [(x, y + 9 * math.sin(x / 180 + i)) for x in range(0, W + 4, 4)]
        d.line(wave, fill=color, width=3)
    ridge(image, [(0, 830), (260, 850), (490, 905), (760, 870), (1020, 1015), (1330, 1080), (1600, 1030)], "#c5baa2")
    d.line([(0, 826), (260, 845), (490, 899), (760, 864), (1020, 1008), (1330, 1073), (1600, 1024)], fill="#dbe0cf", width=9)
    ridge(image, [(0, 720), (170, 660), (265, 735), (300, 885), (0, 1010)], "#29454b")
    d.polygon([(1270, 700), (1380, 570), (1500, 555), (1600, 610), (1600, 900)], fill="#3c5862")
    d.line((1330, 930, 1345, 925, 1361, 931), fill="#c6d6d3", width=3)
    return image


def dunes():
    image = sky((74, 63, 76), (213, 173, 135))
    d = ImageDraw.Draw(image)
    d.ellipse((720, 340, 838, 458), fill="#e1c49b")
    for base, amp, phase, color in [(720, 120, .5, "#b18a72"), (850, 130, 1.7, "#936b5c"), (1010, 160, 3.8, "#634c49")]:
        pts = [(x, base + amp * math.sin(x / 470 + phase)) for x in range(0, W + 4, 4)]
        ridge(image, pts, color)
        d.line(pts, fill={"#b18a72": "#cba88a", "#936b5c": "#b18a72", "#634c49": "#947163"}[color], width=3)
    return image


def stars():
    image = sky((13, 19, 38), (56, 65, 91))
    d = ImageDraw.Draw(image)
    rng = random.Random(42)
    for _ in range(150):
        x, y = rng.randrange(W), rng.randrange(800)
        r = rng.choice([1, 1, 1, 2])
        tone = rng.randrange(100, 200)
        d.ellipse((x - r, y - r, x + r, y + r), fill=(tone, tone, min(220, tone + 15)))
    d.ellipse((720, 220, 810, 310), fill="#bec3c9")
    d.ellipse((745, 207, 820, 286), fill="#1e2943")
    ridge(image, [(0, 1000), (250, 790), (390, 870), (700, 635), (920, 820), (1120, 730), (1410, 900), (1600, 780)], "#202d40")
    ridge(image, [(0, 1090), (350, 1020), (550, 1080), (950, 930), (1250, 1050), (1600, 980)], "#111c2c")
    return image


def main():
    OUT.mkdir(exist_ok=True)
    for name, paint in [("alpine-dusk", mountains), ("cedar-mist", forest), ("quiet-coast", coast),
                        ("desert-glow", dunes), ("starlit-ridge", stars)]:
        image = paint()
        image.save(OUT / f"builtin-{name}.webp", "WEBP", quality=86, method=6)
        image.thumbnail((360, 270))
        image.save(OUT / f"builtin-{name}-thumb.webp", "WEBP", quality=80, method=6)


if __name__ == "__main__":
    main()
