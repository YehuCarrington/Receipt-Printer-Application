from escpos.printer import Usb
from PIL import Image, ImageDraw, ImageFont
import textwrap, logging

# 80mm printers are typically 576 dots wide; 58mm ≈ 384
PRINTER_DOTS = 576          # set to 384 if your unit is 58mm
HEADER_TEXT = "SERVICE DESK"

def render_header(width=PRINTER_DOTS, text=HEADER_TEXT):

    # Canvas
    H = 120  # header height in pixels; tweak if you want taller
    img = Image.new("L", (width, H), 255)  # white background
    draw = ImageDraw.Draw(img)

    # Try monospace bold; fall back gracefully
    font_candidates = [
        "C:/Windows/Fonts/consola.ttf",                 # Consolas
        "C:/Windows/Fonts/consolaz.ttf",                # Consolas Bold Italic
        "C:/Windows/Fonts/lucon.ttf",                   # Lucida Console
        "C:/Windows/Fonts/DejaVuSansMono.ttf",          # If installed
    ]
    fnt = None
    for path in font_candidates:
        try:
            fnt = ImageFont.truetype(path, 64)  # size tuned for 576px width
            break
        except Exception:
            continue
    if fnt is None:
        fnt = ImageFont.load_default()

    # Top/bottom bars
    draw.rectangle((0, 0, width, 10), fill=0)
    draw.rectangle((0, H-10, width, H), fill=0)

    # Text sizing and position
    # Slight negative tracking effect by adding spaces and tightening bbox
    label = text
    tw, th = draw.textbbox((0, 0), label, font=fnt)[2:]
    x = (width - tw) // 2
    y = (H - th) // 2 - 2

    # Draw shadow stroke for extra weight
    for dx, dy in ((-1,0),(1,0),(0,-1),(0,1)):
        draw.text((x+dx, y+dy), label, font=fnt, fill=0)
    draw.text((x, y), label, font=fnt, fill=0)

    # Convert to 1-bit (thermal likes this) with dithering off
    return img.convert("1")



# ----------- Layout -----------
LINE_CHARS = 42            # 80mm ≈ 42; use 32 for 58mm
DIV = "-" * LINE_CHARS
HDR = "=" * LINE_CHARS

# ----------- Logging ----------
log = logging.getLogger("ticket_printer")

def wrap(s, n=LINE_CHARS):
    return "\n".join(textwrap.wrap(s or "", width=n, break_long_words=True))

def get_printer():
    try:
        # Replace with your VID/PID if different
        return Usb(0x067B, 0x2305, timeout=0)
    except Exception as e:
        log.error(f"Failed to initialize printer: {e}")
        return None

def print_ticket(t: dict):
    required = ("id", "title")
    missing = [k for k in required if not t.get(k)]
    if missing:
        raise ValueError(f"Missing required ticket fields: {missing}")

    p = get_printer()
    if p is None:
        raise RuntimeError("Printer not available. Check USB driver/VID/PID or try Win32Raw backend.")

    # Header
    # p.set(align="center", font="a", width=2, height=2)
    # p.text("TICKET\n")

    p.set(align="center")
    header_img = render_header()
    p.image(header_img, impl="bitImageRaster")  # reliable on most ESC/POS units
    p.text("\n")

    p.set(align="center", font="a"); p.text(f"#{t['id']}\n")
    p.set(align="center", font="a"); p.text(wrap(t["title"]) + "\n")
    p.text(HDR + "\n")

    # Body
    p.set(align="center")
    if t.get("description"):
        p.text(wrap(t["description"]) + "\n" + DIV + "\n")

    meta = []
    if t.get("assignee"): meta.append(f"Owner: {t['assignee']}")
    if t.get("priority"): meta.append(f"P: {t['priority']}")
    if meta: p.text(" | ".join(meta) + "\n")
    if t.get("created"): p.text(f"Created: {t['created']}\n")
    p.text(DIV + "\n")

    # QR
    if t.get("url"):
        p.set(align="center"); p.text("Scan for details:\n")
        p.qr(t["url"], size=6, native=True); p.text("\n")

    # Barcode (best effort)
    # try:
    #     p.barcode(str(t["id"]), "CODE128", function_type="B", width=2, height=64, pos="BELOW")
    #     p.text("\n")
    # except Exception as e:
    #     log.warning("Barcode failed: %s", e)

    # --- barcode with fallbacks ---
    code_raw = str(t["id"]).strip()
    code39 = code_raw.upper()
    code128 = code_raw.replace("-", "")

    printed_barcode = False
    try:
        # Try CODE39 first
        p.barcode(code39, "CODE39", width=2, height=64, pos="BELOW")
        printed_barcode = True
    except Exception as e:
        log.warning("CODE39 failed: %s", e)

    if not printed_barcode:
        try:
            # Fallback to CODE128
            p.barcode(code128, "CODE128", function_type="B", width=2, height=64, pos="BELOW")
            printed_barcode = True
        except Exception as e:
            log.warning("CODE128 failed: %s", e)

    if not printed_barcode and t.get("url"):
        
        p.set(align="center"); p.text("(Barcode unavailable — using QR)\n")
        p.qr(t["url"], size=6, native=True)
        p.text("\n")

    # Footer
    if t.get("xp") is not None:
        p.set(align="center", font="a")
        p.text(f"ID: {t['id']} | XP +{t['xp']}\n")

    p.text(HDR + "\n")
    p.cut()

# ----------- CLI glue -----------
if __name__ == "__main__":
    import sys, json, argparse, os

    parser = argparse.ArgumentParser(description="Print a ticket JSON to the thermal printer.")
    parser.add_argument("file", nargs="?", help="Path to JSON file. If omitted, reads JSON from stdin.")
    args = parser.parse_args()

    if args.file:
        if not os.path.exists(args.file):
            raise SystemExit(f"File not found: {args.file}")
        with open(args.file, "r"
                  , encoding="utf-8") as f:
            payload = json.load(f)
    else:
        if sys.stdin.isatty():
            raise SystemExit("No input provided. Pass a JSON filename or pipe JSON via stdin.")
        payload = json.load(sys.stdin)

    print_ticket(payload)