import os
import re
import json
import requests
from bs4 import BeautifulSoup
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


def get_global_and_bank():
    """جلب الأونصة العالمية بالدولار وسعر دولار البنك بالجنيه"""
    gold_res = requests.get("https://api.gold-api.com/price/XAU", timeout=10).json()
    xau_usd = float(gold_res["price"])

    usd_res = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10).json()
    usd_egp = float(usd_res["rates"]["EGP"])

    return xau_usd, usd_egp


def scrape_isagha():
    """سحب أسعار iSagha مباشرة"""
    url = "https://market.isagha.com/prices"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    res = requests.get(url, headers=headers, timeout=15)
    res.raise_for_status()

    soup = BeautifulSoup(res.text, "html.parser")
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))

    def extract_pair(label_pattern):
        m = re.search(
            rf"{label_pattern}.*?(\d{{3,6}}(?:\.\d{{1,2}})?)\s*(?:ج\.م|جنيه)?\s*بيع.*?(\d{{3,6}}(?:\.\d{{1,2}})?)\s*(?:ج\.م|جنيه)?\s*شراء",
            text,
        )
        if m:
            return float(m.group(1)), float(m.group(2))
        return None

    g24 = extract_pair(r"عيار\s*24")
    g21 = extract_pair(r"عيار\s*21")
    g18 = extract_pair(r"عيار\s*18")
    g14 = extract_pair(r"عيار\s*14")
    pound = extract_pair(r"جنيه\s*ذهب")

    if not g21 or not (2500 <= g21[0] <= 25000):
        raise ValueError("Failed to parse 21K price from iSagha")

    g24_sell, g24_buy = g24 if g24 else (g21[0] * 24 / 21, g21[1] * 24 / 21)
    g18_sell, g18_buy = g18 if g18 else (g21[0] * 18 / 21, g21[1] * 18 / 21)
    g14_sell, g14_buy = g14 if g14 else (g21[0] * 14 / 21, g21[1] * 14 / 21)
    p_sell, p_buy = pound if pound else (g21[0] * 8, g21[1] * 8)

    print(f"[iSagha OK] 21K Sell={g21[0]}, Buy={g21[1]}")
    return {
        "g24_sell": g24_sell, "g24_buy": g24_buy,
        "g21_sell": g21[0],   "g21_buy": g21[1],
        "g18_sell": g18_sell, "g18_buy": g18_buy,
        "g14_sell": g14_sell, "g14_buy": g14_buy,
        "pound_sell": p_sell, "pound_buy": p_buy,
    }


def fetch_isagha_gemini():
    """احتياطي Gemini مع بحث جوجل فقط إذا تعذر السكرابينج المباشر"""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY missing")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = (
        "ابحث عن أحدث أسعار الذهب اليوم في مصر من موقع آي صاغة (market.isagha.com/prices). "
        "أعد JSON فقط بدون markdown: "
        '{"g24_sell": 0, "g24_buy": 0, "g21_sell": 0, "g21_buy": 0, "g18_sell": 0, "g18_buy": 0, '
        '"g14_sell": 0, "g14_buy": 0, "pound_sell": 0, "pound_buy": 0}'
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
        raise ValueError("Invalid JSON from Gemini")

    data = json.loads(match.group(0))
    if not (2500 <= float(data["g21_sell"]) <= 25000):
        raise ValueError("Invalid 21K value from Gemini")

    print(f"[Gemini Search OK] 21K Sell={data['g21_sell']}, Buy={data['g21_buy']}")
    return data


def get_prices():
    xau_usd, usd_egp = get_global_and_bank()

    # السعر العالمي المحسوب من الأونصة العالمية ودولار البنك
    global_24 = (xau_usd / OUNCE_GRAMS) * usd_egp
    global_21 = global_24 * (21 / 24)

    sagha = None
    try:
        sagha = scrape_isagha()
    except Exception as e1:
        print(f"[iSagha Scrape Failed] {e1}")
        try:
            sagha = fetch_isagha_gemini()
        except Exception as e2:
            print(f"[Gemini Search Failed] {e2}")

    if sagha:
        g24_sell = float(sagha["g24_sell"])
        g24_buy = float(sagha["g24_buy"])
        g21_sell = float(sagha["g21_sell"])
        g21_buy = float(sagha["g21_buy"])
        g18_sell = float(sagha["g18_sell"])
        g18_buy = float(sagha["g18_buy"])
        g14_sell = float(sagha["g14_sell"])
        g14_buy = float(sagha["g14_buy"])
        pound_sell = float(sagha["pound_sell"])
        pound_buy = float(sagha["pound_buy"])

        # طرح السعر العالمي من سعر الصاغة مباشرة لإخراج الفجوة السعرية
        gap_egp = round(g21_sell - global_21)

        # حساب دولار الصاغة مباشرة نسبةً للسعر العالمي ودولار البنك
        sagha_dollar = usd_egp * (g21_sell / global_21)
    else:
        # في حال تعذر جلب الصاغة من المصدرين، نعرض السعر العالمي بدون فجوة أو افتراضات
        sell_factor = 0.9965
        g24_sell, g24_buy = global_24, global_24 * sell_factor
        g21_sell, g21_buy = global_21, global_21 * sell_factor
        g18_sell, g18_buy = global_24 * (18 / 24), global_24 * (18 / 24) * sell_factor
        g14_sell, g14_buy = global_24 * (14 / 24), global_24 * (14 / 24) * sell_factor
        pound_sell, pound_buy = g21_sell * 8, g21_buy * 8
        gap_egp = 0
        sagha_dollar = usd_egp

    ounce_local_sell = g24_sell * OUNCE_GRAMS
    ounce_local_buy = g24_buy * OUNCE_GRAMS

    return {
        "xau_usd": xau_usd,
        "usd_egp": usd_egp,
        "sagha_dollar": sagha_dollar,
        "gap_egp": gap_egp,
        "global_21": round(global_21),
        "g24_sell": round(g24_sell), "g24_buy": round(g24_buy),
        "g21_sell": round(g21_sell), "g21_buy": round(g21_buy),
        "g18_sell": round(g18_sell), "g18_buy": round(g18_buy),
        "g14_sell": round(g14_sell), "g14_buy": round(g14_buy),
        "pound_sell": round(pound_sell), "pound_buy": round(pound_buy),
        "ounce_sell": round(ounce_local_sell), "ounce_buy": round(ounce_local_buy),
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

    # البطاقات العلوية الثلاثة
    top_y1, top_y2 = 94, 214

    draw.rounded_rectangle([25, top_y1, 275, top_y2], radius=22, fill=EMERALD_DARK, outline=GOLD_ACCENT, width=2)
    draw_centered_text(draw, [25, top_y1 + 8, 275, top_y1 + 56], reshape_ar("دولار البنك"), f_top_title, TEXT_GOLD)
    draw_centered_text(draw, [25, top_y1 + 60, 275, top_y2 - 8], reshape_ar(f"{data['usd_egp']:.2f} ج.م"), f_top_val, TEXT_LIGHT)

    draw.rounded_rectangle([295, top_y1, 605, top_y2], radius=22, fill=CARD_LIGHT, outline=EMERALD_DARK, width=3)
    draw_centered_text(draw, [295, top_y1 + 8, 605, top_y1 + 56], reshape_ar("الأونصة العالمية"), f_top_title, EMERALD_DARK)
    draw_centered_text(draw, [295, top_y1 + 60, 605, top_y2 - 8], reshape_ar(f"{round(data['xau_usd'])} دولار"), f_top_val, TEXT_DARK)

    draw.rounded_rectangle([625, top_y1, 875, top_y2], radius=22, fill=EMERALD_ACCENT, outline=GOLD_ACCENT, width=2)
    draw_centered_text(draw, [625, top_y1 + 8, 875, top_y1 + 56], reshape_ar("دولار الصاغة"), f_top_title, TEXT_GOLD)
    draw_centered_text(draw, [625, top_y1 + 60, 875, top_y2 - 8], reshape_ar(f"{data['sagha_dollar']:.2f} ج.م"), f_top_val, TEXT_LIGHT)

    # كارت عيار 21 الكبير
    draw.rounded_rectangle([25, 236, 875, 685], radius=30, fill=CARD_LIGHT, outline=GOLD_ACCENT, width=4)
    draw.rounded_rectangle([250, 252, 650, 312], radius=20, fill=EMERALD_DARK)
    draw_centered_text(draw, [250, 256, 650, 308], reshape_ar("عيار 21 اليوم في مصر"), f_sec_title, TEXT_GOLD)

    draw_centered_text(draw, [50, 320, 850, 545], f"{data['g21_sell']}", f_big_21, EMERALD_DARK)

    # أزرار بيع / شراء
    draw.rounded_rectangle([55, 562, 435, 658], radius=22, fill=EMERALD_DARK)
    draw_centered_text(draw, [55, 568, 435, 652], reshape_ar(f"بيع: {data['g21_sell']} ج"), f_sub_box, TEXT_GOLD)

    draw.rounded_rectangle([465, 562, 845, 658], radius=22, fill=BG_COLOR, outline=EMERALD_DARK, width=3)
    draw_centered_text(draw, [465, 568, 845, 652], reshape_ar(f"شراء: {data['g21_buy']} ج"), f_sub_box, TEXT_DARK)

    # عناوين الجدول
    draw_centered_text(draw, [50, 712, 250, 780], reshape_ar("شراء"), f_tbl_hdr, TEXT_DARK)
    draw_centered_text(draw, [325, 712, 555, 780], reshape_ar("بيع"), f_tbl_hdr, TEXT_DARK)

    # كارت الفجوة السعرية
    gap_str = f"{data['gap_egp']} ج"
    draw.rounded_rectangle([590, 704, 875, 792], radius=26, fill=CARD_LIGHT, outline=GOLD_ACCENT, width=3)
    draw_centered_text(draw, [598, 710, 725, 786], reshape_ar(gap_str), f_gap_val, EMERALD_DARK)
    draw_centered_text(draw, [725, 710, 868, 786], reshape_ar("الفجوة\nالسعرية"), f_gap_lbl, TEXT_DARK)

    # صفوف الجدول
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

    # الشريط السفلي (السعر العالمي لعيار 21)
    bot_y1, bot_y2 = 1405, 1505
    draw.rounded_rectangle([25, bot_y1, 875, bot_y2], radius=26, fill=EMERALD_DARK, outline=GOLD_ACCENT, width=3)
    draw.rounded_rectangle([38, bot_y1 + 10, 425, bot_y2 - 10], radius=20, fill=CARD_LIGHT)
    draw_centered_text(draw, [38, bot_y1 + 14, 425, bot_y2 - 14], reshape_ar(f"{data['global_21']} جنيه"), f_tbl_hdr, EMERALD_DARK)
    draw_centered_text(draw, [445, bot_y1 + 14, 860, bot_y2 - 14], reshape_ar("سعر عيار 21 عالمياً"), f_tbl_hdr, TEXT_GOLD)

    # الفوتر
    draw_centered_text(draw, [50, 1518, 850, 1578], reshape_ar("@Goldsnowchennel • تحديث تلقائي كل 30 دقيقة"), f_footer, TEXT_DARK)

    img.save(output_path)
    return output_path


def send_photo_to_channel(image_path: str, data: dict):
    cairo_tz = timezone(timedelta(hours=2))
    now = datetime.now(cairo_tz).strftime("%I:%M %p - %Y/%m/%d")
    caption = (
        f"✨ @Goldsnowchennel | ⏰ {now}\n"
        f"💰 عيار 21: {data['g21_sell']} ج.م (شراء: {data['g21_buy']} ج.م)\n"
        f"🌍 الأونصة: ${data['xau_usd']:,.2f} | 💵 البنك: {data['usd_egp']:.2f} | 🪙 الصاغة: {data['sagha_dollar']:.2f}\n"
        f"📊 الفجوة: {data['gap_egp']} ج.م | العالمي 21: {data['global_21']} ج.م"
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
    market_data = get_prices()
    card_path = generate_card(market_data)
    send_photo_to_channel(card_path, market_data)
