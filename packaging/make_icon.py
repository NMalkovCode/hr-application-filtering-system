"""Draw the application icon (packaging/app.ico and hr_screening/resources/app.png)."""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
BLUE, GREEN, WHITE, LINE = (31, 95, 168), (30, 123, 52), (255, 255, 255), (170, 190, 215)


def draw(size: int = 1024) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 256
    d.rounded_rectangle([8 * s, 8 * s, 248 * s, 248 * s], radius=48 * s, fill=BLUE)
    # A document...
    d.rounded_rectangle([62 * s, 40 * s, 170 * s, 200 * s], radius=10 * s, fill=WHITE)
    for i, width in enumerate((80, 64, 80, 52)):
        y = (72 + i * 26) * s
        d.rounded_rectangle([80 * s, y, (80 + width) * s, y + 10 * s], radius=5 * s, fill=LINE)
    # ...with a green tick badge.
    d.ellipse([132 * s, 132 * s, 222 * s, 222 * s], fill=GREEN, outline=WHITE, width=int(8 * s))
    d.line([(154 * s, 178 * s), (171 * s, 195 * s), (201 * s, 160 * s)], fill=WHITE, width=int(13 * s), joint="curve")
    return img


def main() -> None:
    big = draw()
    big.resize((256, 256), Image.Resampling.LANCZOS).save(
        ROOT / "packaging" / "app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    resources = ROOT / "hr_screening" / "resources"
    resources.mkdir(exist_ok=True)
    big.resize((256, 256), Image.Resampling.LANCZOS).save(resources / "app.png")
    print("icon written")


if __name__ == "__main__":
    main()
