import os
import re
import requests
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]

BG_COLOR = (244, 241, 234)
EMERALD_DARK = (15, 46, 38)
EMERALD_ACCENT = (24, 72, 59)
GOLD_ACCENT = (198, 152, 56)
CARD_LIGHT = (255, 253, 249)
TEXT_DARK = (16, 32, 27)
TEXT_LIGHT = (255, 255, 255)
TEXT_GOLD = (242, 206, 115)


def _fallback_rtl(text: str) -> str:
    """عكس ترتيب الأجزاء العربية فقط مع إبقاء الأرقام والرموز كما هي"""
    tokens = re.split(r'(\s+|[0-9]+(?:\.[0-9]+)?|[@A-Za-z0-9_./:-]+)', text)
    ar_tokens = []
    out = []
    for tok in tokens:
        if not tok:
            continue
        if any("\u0600" <= ch <= "\u06FF" for ch in tok):
            ar_tokens.append(tok[::-1])
        else:
            if ar_tokens:
                out.extend(reversed(ar_tokens))
                ar_tokens = []
            out.append(tok)
    if ar_tokens:
        out.extend(reversed(ar_tokens))
    return "".join(out)


def reshape_ar(text: str) -> str:
    """تشكيل وعكس النصوص العربية لتظهر متصلة ومن اليمين لليسار"""
    if not any("\u0600" <= ch <= "\u06FF" for ch in text):
        return text
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        reshaped = arabic_reshaper.reshape(text)
        return get_display(reshaped)
    except Exception as e:
        print(f"Using fallback RTL due to: {e}")
        lines = text.split("\n")
        return "\n".join(_fallback_rtl(line) for line in lines)


def load_font(size: int, bold: bool = False):
    candidates = [
        "font.ttf",
        "Cairo-Bold.ttf",
        "NotoSansArabic-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def get_prices():
    gold_res = requests.get("https://api.gold-api.com/price/XAU", timeout=10).json()
    xau_usd = float(gold_res["price"])

    usd_res = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10).json()
    usd_egp = float(usd_res["rates"]["EGP"])

    return xau_usd, usd_egp


def draw_centered_text(draw, box, text, font, fill):
    x1, y1, x2, y2 = box
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    tx = x1 + (x2 - x1 - w) / 2 - bbox[0]
    ty = y1 + (y2 - y1 - h) / 2 - bbox[1]
    draw.text((tx, ty), text, font=font, fill=fill)


def generate_card(xau_usd: float, usd_egp: float, output_path: str = "gold_card.png"):
    W, H = 900, 1600
    img = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    cairo_tz = timezone(timedelta(hours=2))
    time_str = datetime.now(cairo_tz).strftime("%I:%M %p")

    gram_24_buy = (xau_usd / 31.1034768) * usd_egp
    gram_21_buy = gram_24_buy * (21 / 24)
    gram_18_buy = gram_24_buy * (18 / 24)
    gram_14_buy = gram_24_buy * (14 / 24)
    pound_buy = gram_21_buy * 8
    ounce_local_buy = gram_24_buy * 31.1034768

    sell_factor = 0.9965
    gram_21_sell = gram_21_buy * sell_factor
    gram_24_sell = gram_24_buy * sell_factor
    gram_18_sell = gram_18_buy * sell_factor
    gram_14_sell = gram_14_buy * sell_factor
    pound_sell = pound_buy * sell_factor
    ounce_local_sell = ounce_local_buy * sell_factor

    sagha_dollar = usd_egp
    gap = 0
    fair_21 = round(gram_21_buy)

    f_badge = load_font(24, bold=True)
    f_top_title = load_font(26, bold=True)
    f_top_val = load_font(30, bold=True)
    f_sec_title = load_font(36, bold=True)
    f_big_21 = load_font(150, bold=True)
    f_sub_box = load_font(34, bold=True)
    f_tbl_hdr = load_font(36, bold=True)
    f_row_label = load_font(36, bold=True)
    f_row_num = load_font(40, bold=True)
    f_gap_lbl = load_font(24, bold=True)
    f_gap_val = load_font(32, bold=True)
    f_footer = load_font(26, bold=True)

    draw.rounded_rectangle([25, 22, 875, 76], radius=22, fill=EMERALD_DARK)
    draw.text((48, 34), "GOLD SNOW LIVE", font=f_badge, fill=TEXT_GOLD)
    draw_centered_text(draw, [280, 28, 620, 70], reshape_ar("مؤشر الذهب اللحظي"), f_badge, TEXT_LIGHT)
    draw.text((695, 34), time_str, font=f_badge, fill=TEXT_LIGHT)

    top_y1, top_y2 = 94, 214
    draw.rounded_rectangle([25, top_y1, 275, top_y2], radius=22, fill=EMERALD_DARK, outline=GOLD_ACCENT, width=2)
    draw_centered_text(draw, [25, top_y1 + 8, 275, top_y1 + 56], reshape_ar("دولار البنك"), f_top_title, TEXT_GOLD)
    draw_centered_text(draw, [25, top_y1 + 60, 275, top_y2 - 8], reshape_ar(f"{usd_egp:.2f} ج.م"), f_top_val, TEXT_LIGHT)

    draw.rounded_rectangle([295, top_y1, 605, top_y2], radius=22, fill=CARD_LIGHT, outline=EMERALD_DARK, width=3)
    draw_centered_text(draw, [295, top_y1 + 8, 605, top_y1 + 56], reshape_ar("الأونصة العالمية"), f_top_title, EMERALD_DARK)
    draw_centered_text(draw, [295, top_y1 + 60, 605, top_y2 - 8], reshape_ar(f"{round(xau_usd)} دولار"), f_top_val, TEXT_DARK)

    draw.rounded_rectangle([625, top_y1, 875, top_y2], radius=22, fill=EMERALD_ACCENT, outline=GOLD_ACCENT, width=2)
    draw_centered_text(draw, [625, top_y1 + 8, 875, top_y1 + 56], reshape_ar("دولار الصاغة"), f_top_title, TEXT_GOLD)
    draw_centered_text(draw, [625, top_y1 + 60, 875, top_y2 - 8], reshape_ar(f"{sagha_dollar:.2f} ج.م"), f_top_val, TEXT_LIGHT)

    draw.rounded_rectangle([25, 236, 875, 685], radius=30, fill=CARD_LIGHT, outline=GOLD_ACCENT, width=4)
    draw.rounded_rectangle([250, 252, 650, 312], radius=20, fill=EMERALD_DARK)
    draw_centered_text(draw, [250, 256, 650, 308], reshape_ar("عيار 21 اليوم في مصر"), f_sec_title, TEXT_GOLD)

    draw_centered_text(draw, [50, 320, 850, 545], f"{round(gram_21_buy)}", f_big_21, EMERALD_DARK)

    draw.rounded_rectangle([55, 562, 435, 658], radius=22, fill=EMERALD_DARK)
    draw_centered_text(draw, [55, 568, 435, 652], reshape_ar(f"شراء: {round(gram_21_buy)} ج"), f_sub_box, TEXT_GOLD)

    draw.rounded_rectangle([465, 562, 845, 658], radius=22, fill=BG_COLOR, outline=EMERALD_DARK, width=3)
    draw_centered_text(draw, [465, 568, 845, 652], reshape_ar(f"بيع: {round(gram_21_sell)} ج"), f_sub_box, TEXT_DARK)

    draw_centered_text(draw, [50, 712, 250, 780], reshape_ar("بيع"), f_tbl_hdr, TEXT_DARK)
    draw_centered_text(draw, [325, 712, 555, 780], reshape_ar("شراء"), f_tbl_hdr, TEXT_DARK)
    draw.rounded_rectangle([605, 704, 875, 792], radius=26, fill=CARD_LIGHT, outline=GOLD_ACCENT, width=3)
    draw.text((628, 730), f"{gap}", font=f_gap_val, fill=EMERALD_DARK)
    draw_centered_text(draw, [665, 710, 868, 786], reshape_ar("الفجوة\nالسعرية"), f_gap_lbl, TEXT_DARK)

    rows = [
        ("عيار 24", round(gram_24_buy), round(gram_24_sell)),
        ("عيار 18", round(gram_18_buy), round(gram_18_sell)),
        ("عيار 14", round(gram_14_buy), round(gram_14_sell)),
        ("جنيه الذهب", round(pound_buy), round(pound_sell)),
        ("أونصة محلى", round(ounce_local_buy), round(ounce_local_sell)),
    ]

    start_y = 812
    row_h = 94
    gap_y = 15

    for idx, (label, buy_val, sell_val) in enumerate(rows):
        y1 = start_y + idx * (row_h + gap_y)
        y2 = y1 + row_h
        row_bg = EMERALD_DARK if idx % 2 == 0 else EMERALD_ACCENT
        draw.rounded_rectangle([25, y1, 875, y2], radius=24, fill=row_bg)

        draw.ellipse([48, y1 + 35, 74, y1 + 61], fill=TEXT_GOLD)

        draw_centered_text(draw, [92, y1 + 10, 285, y2 - 10], f"{sell_val}", f_row_num, TEXT_LIGHT)
        draw_centered_text(draw, [315, y1 + 10, 565, y2 - 10], f"{buy_val}", f_row_num, TEXT_GOLD)
        draw_centered_text(draw, [585, y1 + 10, 860, y2 - 10], reshape_ar(label), f_row_label, TEXT_LIGHT)

    bot_y1, bot_y2 = 1405, 1505
    draw.rounded_rectangle([25, bot_y1, 875, bot_y2], radius=26, fill=EMERALD_DARK, outline=GOLD_ACCENT, width=3)
    draw.rounded_rectangle([38, bot_y1 + 10, 425, bot_y2 - 10], radius=20, fill=CARD_LIGHT)
    draw_centered_text(draw, [38, bot_y1 + 14, 425, bot_y2 - 14], reshape_ar(f"{fair_21} جنيه"), f_tbl_hdr, EMERALD_DARK)
    draw_centered_text(draw, [445, bot_y1 + 14, 860, bot_y2 - 14], reshape_ar("سعر عيار 21 العادل"), f_tbl_hdr, TEXT_GOLD)

    draw_centered_text(draw, [50, 1518, 850, 1578], reshape_ar("@Goldsnowchennel • تحديث تلقائي كل 30 دقيقة"), f_footer, TEXT_DARK)

    img.save(output_path)
    return output_path


def send_photo_to_channel(image_path: str, xau_usd: float, usd_egp: float):
    cairo_tz = timezone(timedelta(hours=2))
    now = datetime.now(cairo_tz).strftime("%I:%M %p - %Y/%m/%d")
    caption = f"✨ @Goldsnowchennel | ⏰ {now}\n🌍 XAU/USD: ${xau_usd:,.2f} | 💵 USD/EGP: {usd_egp:.2f}"

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    with open(image_path, "rb") as photo_file:
        res = requests.post(
            url,
            data={"chat_id": CHANNEL_ID, "caption": caption},
            files={"photo": photo_file},
            timeout=20,
        )
    print(res.text)


if __name__ == "__main__":
    xau, egp = get_prices()
    card_path = generate_card(xau, egp)
    send_photo_to_channel(card_path, xau, egp)
