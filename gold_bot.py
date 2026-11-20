import os
import re
import json
import requests
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

BG_COLOR = (244, 241, 234)
EMERALD_DARK = (15, 46, 38)
EMERALD_ACCENT = (24, 72, 59)
GOLD_ACCENT = (198, 152, 56)
CARD_LIGHT = (255, 253, 249)
TEXT_DARK = (16, 32, 27)
TEXT_LIGHT = (255, 255, 255)
TEXT_GOLD = (242, 206, 115)

OUNCE_GRAMS = 31.1034768


def reshape_ar(text: str) -> str:
    return text


def load_font(size: int, bold: bool = False):
    candidates = [
        "font.ttf",
        "Cairo-Bold.ttf",
        "NotoSansArabic-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def get_global_market():
    """جلب الأونصة العالمية ودولار البنك وحساب كل الأعيرة من الشاشة العالمية"""
    gold_res = requests.get("https://api.gold-api.com/price/XAU", timeout=10).json()
    xau_usd = float(gold_res["price"])

    usd_res = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10).json()
    usd_egp = float(usd_res["rates"]["EGP"])

    global_24_sell = (xau_usd / OUNCE_GRAMS) * usd_egp
    global_21_sell = global_24_sell * (21 / 24)
    global_18_sell = global_24_sell * (18 / 24)
    global_14_sell = global_24_sell * (14 / 24)
    global_pound_sell = global_21_sell * 8
    global_ounce_sell = global_24_sell * OUNCE_GRAMS

    # فارق بسيط للشراء من الشاشة العالمية
    buy_factor = 0.9965
    return {
        "xau_usd": xau_usd,
        "usd_egp": usd_egp,
        "g24_sell": round(global_24_sell), "g24_buy": round(global_24_sell * buy_factor),
        "g21_sell": round(global_21_sell), "g21_buy": round(global_21_sell * buy_factor),
        "g18_sell": round(global_18_sell), "g18_buy": round(global_18_sell * buy_factor),
        "g14_sell": round(global_14_sell), "g14_buy": round(global_14_sell * buy_factor),
        "pound_sell": round(global_pound_sell), "pound_buy": round(global_pound_sell * buy_factor),
        "ounce_sell": round(global_ounce_sell), "ounce_buy": round(global_ounce_sell * buy_factor),
    }


def get_isagha_21_via_gemini(fallback_sell: float, fallback_buy: float):
    """جيميناي يبحث في آي صاغة (isagha) ويجيب سعر الجرام عيار 21 بيع وشراء"""
    if not GEMINI_API_KEY:
        print("[Gemini Warning] GEMINI_API_KEY missing, using global 21K fallback.")
        return fallback_sell, fallback_buy

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = (
            "ابحث في موقع آي صاغة (isagha) عن سعر جرام الذهب عيار 21 اليوم في مصر الآن (سعر البيع وسعر الشراء). "
            "أعد النتيجة بصيغة JSON فقط بدون أي كلام إضافي أو markdown: "
            '{"g21_sell": 0, "g21_buy": 0}'
        )
        res = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[{"google_search": {}}],
                temperature=0.1,
            ),
        )
        match = re.search(r"\{.*\}", res.text.strip(), re.DOTALL)
        if not match:
            raise ValueError(f"No JSON found in Gemini response: {res.text}")

        data = json.loads(match.group(0))
        sell_val = float(data["g21_sell"])
        buy_val = float(data.get("g21_buy") or sell_val)

        # التحقق من أن الرقم منطقي لسعر جرام 21 في مصر
        if not (2500 <= sell_val <= 30000):
            raise ValueError(f"Unrealistic 21K price from Gemini: {sell_val}")

        print(f"[Gemini iSagha OK] 21K Sell={sell_val}, Buy={buy_val}")
        return round(sell_val), round(buy_val)

    except Exception as e:
        print(f"[Gemini iSagha Error] {e}")
        return round(fallback_sell), round(fallback_buy)


def build_market_data():
    glob = get_global_market()
    sagha_21_sell, sagha_21_buy = get_isagha_21_via_gemini(
        fallback_sell=glob["g21_sell"],
        fallback_buy=glob["g21_buy"],
    )

    # الفجوة السعرية = سعر عيار 21 في آي صاغة - سعر عيار 21 من الشاشة العالمية
    gap_egp = sagha_21_sell - glob["g21_sell"]

    return {
        "xau_usd": glob["xau_usd"],
        "usd_egp": glob["usd_egp"],
        "sagha_21_sell": sagha_21_sell,
        "sagha_21_buy": sagha_21_buy,
        "gap_egp": gap_egp,
        "global_21_sell": glob["g21_sell"],
        "g24_sell": glob["g24_sell"], "g24_buy": glob["g24_buy"],
        "g18_sell": glob["g18_sell"], "g18_buy": glob["g18_buy"],
        "g14_sell": glob["g14_sell"], "g14_buy": glob["g14_buy"],
        "pound_sell": glob["pound_sell"], "pound_buy": glob["pound_buy"],
        "ounce_sell": glob["ounce_sell"], "ounce_buy": glob["ounce_buy"],
    }


def draw_centered_text(draw, box, text, font, fill):
    x1, y1, x2, y2 = box
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    tx = x1 + (x2 - x1 - w) / 2 - bbox[0]
    ty = y1 + (y2 - y1 - h) / 2 - bbox[1]
    draw.text((tx, ty), text, font=font, fill=fill)


def generate_card(data: dict, output_path: str = "gold_card.png"):
    W, H = 900, 1600
    img = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    cairo_tz = timezone(timedelta(hours=2))
    time_str = datetime.now(cairo_tz).strftime("%I:%M %p")

    f_badge = load_font(24, bold=True)
    f_top_title = load_font(26, bold=True)
    f_top_val = load_font(30, bold=True)
    f_sec_title = load_font(36, bold=True)
    f_big_21 = load_font(150, bold=True)
    f_sub_box = load_font(34, bold=True)
    f_tbl_hdr = load_font(36, bold=True)
    f_row_label = load_font(36, bold=True)
    f_row_num = load_font(40, bold=True)
    f_gap_lbl = load_font(23, bold=True)
    f_gap_val = load_font(30, bold=True)
    f_footer = load_font(26, bold=True)

    # الشريط العلوي
    draw.rounded_rectangle([25, 22, 875, 76], radius=22, fill=EMERALD_DARK)
    draw.text((48, 34), "GOLD SNOW LIVE", font=f_badge, fill=TEXT_GOLD)
    draw_centered_text(draw, [280, 28, 620, 70], reshape_ar("مؤشر الذهب اللحظي"), f_badge, TEXT_LIGHT)
    draw.text((695, 34), time_str, font=f_badge, fill=TEXT_LIGHT)

    # البطاقات العلوية (دولار البنك + الأونصة العالمية)
    top_y1, top_y2 = 94, 214

    draw.rounded_rectangle([25, top_y1, 435, top_y2], radius=22, fill=EMERALD_DARK, outline=GOLD_ACCENT, width=2)
    draw_centered_text(draw, [25, top_y1 + 8, 435, top_y1 + 56], reshape_ar("دولار البنك"), f_top_title, TEXT_GOLD)
    draw_centered_text(draw, [25, top_y1 + 60, 435, top_y2 - 8], reshape_ar(f"{data['usd_egp']:.2f} ج.م"), f_top_val, TEXT_LIGHT)

    draw.rounded_rectangle([465, top_y1, 875, top_y2], radius=22, fill=CARD_LIGHT, outline=EMERALD_DARK, width=3)
    draw_centered_text(draw, [465, top_y1 + 8, 875, top_y1 + 56], reshape_ar("الأونصة العالمية"), f_top_title, EMERALD_DARK)
    draw_centered_text(draw, [465, top_y1 + 60, 875, top_y2 - 8], reshape_ar(f"{round(data['xau_usd'])} دولار"), f_top_val, TEXT_DARK)

    # كارت عيار 21 اليوم في مصر (من آي صاغة عبر جيميناي)
    draw.rounded_rectangle([25, 236, 875, 685], radius=30, fill=CARD_LIGHT, outline=GOLD_ACCENT, width=4)
    draw.rounded_rectangle([250, 252, 650, 312], radius=20, fill=EMERALD_DARK)
    draw_centered_text(draw, [250, 256, 650, 308], reshape_ar("عيار 21 اليوم في مصر"), f_sec_title, TEXT_GOLD)

    draw_centered_text(draw, [50, 320, 850, 545], f"{data['sagha_21_sell']}", f_big_21, EMERALD_DARK)

    draw.rounded_rectangle([55, 562, 435, 658], radius=22, fill=EMERALD_DARK)
    draw_centered_text(draw, [55, 568, 435, 652], reshape_ar(f"بيع: {data['sagha_21_sell']} ج"), f_sub_box, TEXT_GOLD)

    draw.rounded_rectangle([465, 562, 845, 658], radius=22, fill=BG_COLOR, outline=EMERALD_DARK, width=3)
    draw_centered_text(draw, [465, 568, 845, 652], reshape_ar(f"شراء: {data['sagha_21_buy']} ج"), f_sub_box, TEXT_DARK)

    # عناوين الجدول
    draw_centered_text(draw, [50, 712, 250, 780], reshape_ar("شراء"), f_tbl_hdr, TEXT_DARK)
    draw_centered_text(draw, [325, 712, 555, 780], reshape_ar("بيع"), f_tbl_hdr, TEXT_DARK)

    # كارت الفجوة السعرية (آي صاغة - الشاشة العالمية)
    gap_val = data["gap_egp"]
    gap_str = f"{gap_val:+d} ج" if gap_val != 0 else "0 ج"
    draw.rounded_rectangle([590, 704, 875, 792], radius=26, fill=CARD_LIGHT, outline=GOLD_ACCENT, width=3)
    draw_centered_text(draw, [598, 710, 725, 786], reshape_ar(gap_str), f_gap_val, EMERALD_DARK)
    draw_centered_text(draw, [725, 710, 868, 786], reshape_ar("الفجوة\nالسعرية"), f_gap_lbl, TEXT_DARK)

    # باقي الأعيرة كلها من الشاشة العالمية
    rows = [
        ("عيار 24", data["g24_sell"], data["g24_buy"]),
        ("عيار 18", data["g18_sell"], data["g18_buy"]),
        ("عيار 14", data["g14_sell"], data["g14_buy"]),
        ("جنيه الذهب", data["pound_sell"], data["pound_buy"]),
        ("أونصة محلى", data["ounce_sell"], data["ounce_buy"]),
    ]

    start_y = 812
    row_h = 94
    gap_y = 15

    for idx, (label, sell_val, buy_val) in enumerate(rows):
        y1 = start_y + idx * (row_h + gap_y)
        y2 = y1 + row_h
        row_bg = EMERALD_DARK if idx % 2 == 0 else EMERALD_ACCENT
        draw.rounded_rectangle([25, y1, 875, y2], radius=24, fill=row_bg)

        draw.ellipse([48, y1 + 35, 74, y1 + 61], fill=TEXT_GOLD)

        draw_centered_text(draw, [92, y1 + 10, 285, y2 - 10], f"{buy_val}", f_row_num, TEXT_LIGHT)
        draw_centered_text(draw, [315, y1 + 10, 565, y2 - 10], f"{sell_val}", f_row_num, TEXT_GOLD)
        draw_centered_text(draw, [585, y1 + 10, 860, y2 - 10], reshape_ar(label), f_row_label, TEXT_LIGHT)

    # الشريط السفلي (سعر عيار 21 من الشاشة العالمية)
    bot_y1, bot_y2 = 1405, 1505
    draw.rounded_rectangle([25, bot_y1, 875, bot_y2], radius=26, fill=EMERALD_DARK, outline=GOLD_ACCENT, width=3)
    draw.rounded_rectangle([38, bot_y1 + 10, 425, bot_y2 - 10], radius=20, fill=CARD_LIGHT)
    draw_centered_text(draw, [38, bot_y1 + 14, 425, bot_y2 - 14], reshape_ar(f"{data['global_21_sell']} جنيه"), f_tbl_hdr, EMERALD_DARK)
    draw_centered_text(draw, [445, bot_y1 + 14, 860, bot_y2 - 14], reshape_ar("سعر عيار 21 عالمياً"), f_tbl_hdr, TEXT_GOLD)

    # الفوتر
    draw_centered_text(draw, [50, 1518, 850, 1578], reshape_ar("@Goldsnowchennel • تحديث تلقائي كل 30 دقيقة"), f_footer, TEXT_DARK)

    img.save(output_path)
    return output_path


def send_photo_to_channel(image_path: str, data: dict):
    cairo_tz = timezone(timedelta(hours=2))
    now = datetime.now(cairo_tz).strftime("%I:%M %p - %Y/%m/%d")
    gap_val = data["gap_egp"]
    gap_str = f"{gap_val:+d}" if gap_val != 0 else "0"
    caption = (
        f"✨ @Goldsnowchennel | ⏰ {now}\n"
        f"💰 عيار 21 (آي صاغة): {data['sagha_21_sell']} ج.م (شراء: {data['sagha_21_buy']} ج.م)\n"
        f"🌍 الأونصة: ${data['xau_usd']:,.2f} | 💵 البنك: {data['usd_egp']:.2f} | عيار 21 عالمي: {data['global_21_sell']} ج.م\n"
        f"📊 الفجوة السعرية: {gap_str} ج.م"
    )

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
    market_data = build_market_data()
    card_path = generate_card(market_data)
    send_photo_to_channel(card_path, market_data)
