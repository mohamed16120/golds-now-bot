import os
import time
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


def get_global_market():
    """جلب الأونصة العالمية ودولار البنك وحساب كل الأعيرة من الشاشة العالمية"""
    gold_res = get_json("https://api.gold-api.com/price/XAU")
    xau_usd = float(gold_res["price"])

    usd_res = get_json("https://open.er-api.com/v6/latest/USD")
    usd_egp = float(usd_res["rates"]["EGP"])

    global_24 = (xau_usd / OUNCE_GRAMS) * usd_egp
    global_21 = global_24 * (21 / 24)
    global_18 = global_24 * (18 / 24)
    global_14 = global_24 * (14 / 24)
    global_pound = global_21 * 8
    global_ounce = global_24 * OUNCE_GRAMS

    return {
        "xau_usd": xau_usd,
        "usd_egp": usd_egp,
        "g24_sell": round(global_24), "g24_buy": round(global_24),
        "g21_sell": round(global_21), "g21_buy": round(global_21),
        "g18_sell": round(global_18), "g18_buy": round(global_18),
        "g14_sell": round(global_14), "g14_buy": round(global_14),
        "pound_sell": round(global_pound), "pound_buy": round(global_pound),
        "ounce_sell": round(global_ounce), "ounce_buy": round(global_ounce),
    }


def get_json(url: str, tries: int = 3):
    last = None
    for _ in range(tries):
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            time.sleep(3)
    raise last


def scrape_isagha_21():
    """Reads the 21K row from the price table on isagha.com (columns: buy, sell)."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    res = requests.get("https://isagha.com/", headers=headers, timeout=15)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) >= 3 and re.fullmatch(r"عيار\s*21", cells[0]):
            buy_val = float(cells[1].replace(",", ""))
            sell_val = float(cells[2].replace(",", ""))
            if 2500 <= sell_val <= 30000 and 0 <= sell_val - buy_val < 0.1 * sell_val:
                print(f"[iSagha Scrape OK] Sell={sell_val}, Buy={buy_val}")
                return round(sell_val), round(buy_val)
    raise ValueError("21K row not found or values look wrong on isagha.com")


def get_isagha_21_via_gemini(fallback_sell: int, fallback_buy: int):
    """محاولة احتياطية: جيميناي يبحث حصرياً في isagha.com عن سعر عيار 21"""
    if not GEMINI_API_KEY:
        print("[Gemini Warning] GEMINI_API_KEY is empty.")
        return fallback_sell, fallback_buy

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = (
            'ابحث حصرياً في موقع آي صاغة باستخدام site:isagha.com عن أحدث سعر لجرام الذهب عيار 21 في مصر الآن '
            '(سعر البيع وسعر الشراء من isagha.com فقط دون أي مواقع أخرى). '
            'أعد النتيجة بصيغة JSON فقط بدون أي نص إضافي أو markdown: '
            '{"g21_sell": 0, "g21_buy": 0}'
        )
        res = client.models.generate_content(
            model=os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[{"google_search": {}}],
                temperature=0.0,
            ),
        )
        raw_text = (res.text or "").strip()
        print(f"[Gemini iSagha Raw] {raw_text}")

        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if not match:
            raise ValueError("No JSON object returned by Gemini")

        data = json.loads(match.group(0))
        sell_val = float(data["g21_sell"])
        buy_val = float(data.get("g21_buy") or sell_val)

        if not (2500 <= sell_val <= 30000):
            raise ValueError(f"Unrealistic 21K price: {sell_val}")

        print(f"[Gemini iSagha OK] Sell={round(sell_val)}, Buy={round(buy_val)}")
        return round(sell_val), round(buy_val)

    except Exception as e:
        print(f"[Gemini iSagha Error] {repr(e)}")
        return fallback_sell, fallback_buy


def build_market_data():
    glob = get_global_market()

    try:
        sagha_21_sell, sagha_21_buy = scrape_isagha_21()
    except Exception as e_scrape:
        print(f"[Fallback to Gemini] {repr(e_scrape)}")
        sagha_21_sell, sagha_21_buy = get_isagha_21_via_gemini(
            fallback_sell=glob["g21_sell"],
            fallback_buy=glob["g21_buy"],
        )

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
    W, H = 900, 1390
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
    f_big_glob = load_font(80, bold=True)

    draw.rounded_rectangle([25, 22, 875, 76], radius=22, fill=EMERALD_DARK)
    draw.text((48, 34), "GOLD SNOW LIVE", font=f_badge, fill=TEXT_GOLD)
    draw_centered_text(draw, [280, 28, 620, 70], reshape_ar("مؤشر الذهب اللحظي"), f_badge, TEXT_LIGHT)
    draw.text((695, 34), time_str, font=f_badge, fill=TEXT_LIGHT)

    # ---- Egypt card (top) ----
    draw.rounded_rectangle([25, 94, 875, 464], radius=30, fill=CARD_LIGHT, outline=GOLD_ACCENT, width=4)
    draw.rounded_rectangle([200, 108, 700, 166], radius=20, fill=EMERALD_DARK)
    draw_centered_text(draw, [200, 110, 700, 164], reshape_ar("مصر | عيار 21 (آي صاغة)"), f_sec_title, TEXT_GOLD)
    draw_centered_text(draw, [50, 176, 850, 330], f"{data['sagha_21_sell']}", f_big_21, EMERALD_DARK)
    draw.rounded_rectangle([55, 346, 435, 442], radius=22, fill=EMERALD_DARK)
    draw_centered_text(draw, [55, 350, 435, 438], reshape_ar(f"بيع: {data['sagha_21_sell']} ج"), f_sub_box, TEXT_GOLD)
    draw.rounded_rectangle([465, 346, 845, 442], radius=22, fill=BG_COLOR, outline=EMERALD_DARK, width=3)
    draw_centered_text(draw, [465, 350, 845, 438], reshape_ar(f"شراء: {data['sagha_21_buy']} ج"), f_sub_box, TEXT_DARK)

    # ---- Global card, directly under Egypt ----
    draw.rounded_rectangle([25, 480, 875, 800], radius=30, fill=EMERALD_DARK, outline=GOLD_ACCENT, width=4)
    draw_centered_text(draw, [200, 490, 700, 540], reshape_ar("عالمياً"), f_sec_title, TEXT_GOLD)
    draw.rounded_rectangle([45, 552, 435, 700], radius=22, fill=CARD_LIGHT)
    draw_centered_text(draw, [45, 556, 435, 604], reshape_ar("الأونصة"), f_top_title, EMERALD_DARK)
    draw_centered_text(draw, [45, 600, 435, 696], reshape_ar(f"${data['xau_usd']:,.0f}"), f_big_glob, EMERALD_DARK)
    draw.rounded_rectangle([465, 552, 855, 700], radius=22, fill=CARD_LIGHT)
    draw_centered_text(draw, [465, 556, 855, 604], reshape_ar("عيار 21 عالمي"), f_top_title, EMERALD_DARK)
    draw_centered_text(draw, [465, 600, 855, 696], reshape_ar(f"{data['global_21_sell']} ج"), f_big_glob, EMERALD_DARK)

    gap_val = data["gap_egp"]
    gap_str = f"{gap_val:+d} ج" if gap_val != 0 else "0 ج"
    draw_centered_text(draw, [45, 712, 435, 786], reshape_ar(f"دولار البنك: {data['usd_egp']:.2f} ج"), f_gap_val, TEXT_LIGHT)
    draw_centered_text(draw, [465, 712, 855, 786], reshape_ar(f"الفجوة السعرية: {gap_str}"), f_gap_val, TEXT_GOLD)

    # ---- Other karats ----
    draw_centered_text(draw, [50, 818, 250, 880], reshape_ar("شراء"), f_tbl_hdr, TEXT_DARK)
    draw_centered_text(draw, [325, 818, 555, 880], reshape_ar("بيع"), f_tbl_hdr, TEXT_DARK)

    rows = [
        ("عيار 24", data["g24_sell"], data["g24_buy"]),
        ("عيار 18", data["g18_sell"], data["g18_buy"]),
        ("عيار 14", data["g14_sell"], data["g14_buy"]),
        ("جنيه الذهب", data["pound_sell"], data["pound_buy"]),
    ]

    start_y = 890
    row_h = 90
    gap_y = 14

    for idx, (label, sell_val, buy_val) in enumerate(rows):
        y1 = start_y + idx * (row_h + gap_y)
        y2 = y1 + row_h
        row_bg = EMERALD_DARK if idx % 2 == 0 else EMERALD_ACCENT
        draw.rounded_rectangle([25, y1, 875, y2], radius=24, fill=row_bg)
        draw.ellipse([48, y1 + 32, 74, y1 + 58], fill=TEXT_GOLD)
        draw_centered_text(draw, [92, y1 + 10, 285, y2 - 10], f"{buy_val}", f_row_num, TEXT_LIGHT)
        draw_centered_text(draw, [315, y1 + 10, 565, y2 - 10], f"{sell_val}", f_row_num, TEXT_GOLD)
        draw_centered_text(draw, [585, y1 + 10, 860, y2 - 10], reshape_ar(label), f_row_label, TEXT_LIGHT)

    draw_centered_text(draw, [50, 1310, 850, 1370], reshape_ar("@Goldsnowchennel • تحديث تلقائي كل ساعة"), f_footer, TEXT_DARK)

    img.save(output_path)
    return output_path


def send_photo_to_channel(image_path: str, data: dict):
    cairo_tz = timezone(timedelta(hours=2))
    now = datetime.now(cairo_tz).strftime("%I:%M %p - %Y/%m/%d")
    gap_val = data["gap_egp"]
    gap_str = f"{gap_val:+d}" if gap_val != 0 else "0"
    caption = (
        f"💰 مصر عيار 21 (آي صاغة): بيع {data['sagha_21_sell']} | شراء {data['sagha_21_buy']} ج.م\n"
        f"🌍 عالمي: الأونصة ${data['xau_usd']:,.2f} | عيار 21 {data['global_21_sell']} ج.م\n"
        f"📊 الفجوة {gap_str} ج.م | 💵 {data['usd_egp']:.2f}\n"
        f"⏰ {now} | @Goldsnowchennel"
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
    res.raise_for_status()
    if not res.json().get("ok"):
        raise SystemExit("Telegram rejected the post")


if __name__ == "__main__":
    market_data = build_market_data()
    card_path = generate_card(market_data)
    send_photo_to_channel(card_path, market_data)
