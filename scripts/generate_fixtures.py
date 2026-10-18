from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "data/fixtures/public"
FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
FONT_BOLD = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def draw_headphones(image: Image.Image) -> None:
    draw = ImageDraw.Draw(image)
    draw.arc((360, 180, 840, 660), 190, 350, fill="#29394b", width=48)
    draw.rounded_rectangle((338, 395, 465, 615), radius=48, fill="#29394b")
    draw.rounded_rectangle((735, 395, 862, 615), radius=48, fill="#29394b")
    draw.rounded_rectangle((365, 420, 440, 590), radius=34, fill="#537a91")
    draw.rounded_rectangle((760, 420, 835, 590), radius=34, fill="#537a91")
    draw.ellipse((388, 453, 417, 482), fill="#d7e4e9")
    draw.ellipse((783, 453, 812, 482), fill="#d7e4e9")
    draw.rounded_rectangle((430, 218, 770, 263), radius=20, fill="#405a70")


def main() -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    base = Image.new("RGB", (1200, 800), "#eef4f6")
    draw = ImageDraw.Draw(base)
    draw.ellipse((180, 90, 1020, 930), fill="#e2edf0")
    draw.text((70, 52), "AEROBEAT", font=ImageFont.truetype(FONT_BOLD, 30), fill="#28404f")
    draw.text(
        (72, 98), "AB-01  •  SYNTHETIC DEMO", font=ImageFont.truetype(FONT, 18), fill="#526b78"
    )
    draw_headphones(base)
    base.save(PUBLIC / "aerobeat-neutral.png", format="PNG", optimize=True)

    promo = base.copy()
    promo_draw = ImageDraw.Draw(promo)
    promo_draw.rounded_rectangle(
        (775, 80, 1110, 192), radius=24, fill="#fff4df", outline="#d8832f", width=4
    )
    promo_draw.text((815, 112), "Only $49", font=ImageFont.truetype(FONT_BOLD, 46), fill="#7c381d")
    promo.save(PUBLIC / "aerobeat-only49.png", format="PNG", optimize=True)
    promo.filter(ImageFilter.GaussianBlur(radius=15)).save(
        PUBLIC / "aerobeat-blurry.png", format="PNG", optimize=True
    )
    base.save(PUBLIC / "aerobeat-neutral.jpg", format="JPEG", quality=91, optimize=True)


if __name__ == "__main__":
    main()
