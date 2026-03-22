"""
全フォントバリアントを統合したtemplates.jsonを生成。
- narrow: スクショキャプチャ（名前入力/ポケモン名等）
- normal/male/female: pretフォントPNG（通常メッセージ）
"""
import json
import re
import sys
from pathlib import Path

from PIL import Image
import numpy as np

# ===== 定数 =====
FONTS_DIR = Path("games/pokemon-firered/fonts")
CHARMAP_PATH = FONTS_DIR / "charmap.txt"
CHARS_OUT = Path("chars_out")
OUTPUT_PATH = Path("games/pokemon-firered/templates.json")

# pretフォント設定
CELL_W, CELL_H = 16, 16
CHAR_W, CHAR_H = 10, 12
GRID_COLS = 16

PALETTE_TO_GRAY = {
    0: -1,    # 背景 → 透明
    1: 0,     # アウトライン (黒) → 残す
    2: 64,    # 影 → 残す
    3: -1,    # 文字塗り（明るいグレー） → 透明
}

# narrowテンプレートの背景色閾値（この範囲の輝度は背景とみなして-1にする）
NARROW_BG_MIN = 130
NARROW_BG_MAX = 210

FONT_VARIANTS = {
    "normal": FONTS_DIR / "japanese_normal.png",
    "male": FONTS_DIR / "japanese_male.png",
    "female": FONTS_DIR / "japanese_female.png",
    "bold": FONTS_DIR / "japanese_bold.png",
    "small": FONTS_DIR / "japanese_small.png",
    "tall": FONTS_DIR / "japanese_tall.png",
}


def parse_charmap(charmap_path: Path) -> dict[str, int]:
    """charmap.txtをパースして {文字: PNGセルインデックス} を返す"""
    result: dict[str, int] = {}
    pattern = re.compile(r"^'(.+?)'(?:\s+)?=\s+([0-9A-Fa-f]{2,3})\s*$")
    with charmap_path.open(encoding="utf-8") as f:
        for line in f:
            line = re.sub(r"^\s*\d+→", "", line).strip()
            if not line or line.startswith("@"):
                continue
            m = pattern.match(line)
            if m and m.group(1) not in result:
                result[m.group(1)] = int(m.group(2), 16)
    return result


def is_target_char(char: str) -> bool:
    if len(char) > 1:
        # 複数文字エントリ (Lv, PP, ID, No等) も対象
        return True
    cp = ord(char)
    if 0x3041 <= cp <= 0x3096:  # ひらがな
        return True
    if 0x30A0 <= cp <= 0x30FF:  # カタカナ
        return True
    if char.isalnum() and cp < 0x80:  # ASCII英数字
        return True
    if char in set("!?.-,/()&+=%<>:;×♂♀！？。ー▶『』「」・…円◎△↑↓←→＋①②③④⑤⑥⑦⑧⑨_✚$"):
        return True
    return False


def extract_pret_variant(png_path: Path, char_to_idx: dict[str, int],
                         grid_cols: int = GRID_COLS,
                         cell_w: int = CELL_W, cell_h: int = CELL_H,
                         offset_x: int = 0, offset_y: int = 0,
                         char_w: int = CHAR_W, char_h: int = CHAR_H,
                         auto_bbox: bool = False) -> tuple[dict[str, dict], int, int]:
    """pretフォントPNGから全文字テンプレートを抽出。
    auto_bbox=True: bounding box切り出し→char_w x char_hにパディング
    auto_bbox=False: cell_w x cell_h + offset で切り出し、char_w x char_h で保存
    Returns: (templates, actual_w, actual_h)
    """
    palette_img = Image.open(png_path)
    templates = {}

    for char, png_index in char_to_idx.items():
        if not is_target_char(char):
            continue
        col = png_index % grid_cols
        row = png_index // grid_cols
        x0 = col * cell_w + offset_x
        y0 = row * cell_h + offset_y
        if y0 + char_h > palette_img.height or x0 + char_w > palette_img.width:
            continue

        cell = palette_img.crop((x0, y0, x0 + char_w, y0 + char_h))
        raw = list(cell.tobytes())

        has_content = any(p != 0 for p in raw)
        if not has_content:
            continue

        if auto_bbox:
            # bounding box → 中央揃えパディング
            min_x, min_y, max_x, max_y = char_w, char_h, 0, 0
            for cy in range(char_h):
                for cx in range(char_w):
                    if raw[cy * char_w + cx] != 0:
                        min_x = min(min_x, cx)
                        min_y = min(min_y, cy)
                        max_x = max(max_x, cx)
                        max_y = max(max_y, cy)
            bw = max_x - min_x + 1
            bh = max_y - min_y + 1
            bbox_cell = palette_img.crop((x0 + min_x, y0 + min_y, x0 + max_x + 1, y0 + max_y + 1))
            bbox_raw = list(bbox_cell.tobytes())
            bbox_pixels = [PALETTE_TO_GRAY.get(p, -1) for p in bbox_raw]
            padded = [-1] * (char_w * char_h)
            ox = (char_w - bw) // 2
            oy = (char_h - bh) // 2
            for cy in range(bh):
                for cx in range(bw):
                    tx, ty = ox + cx, oy + cy
                    if 0 <= tx < char_w and 0 <= ty < char_h:
                        padded[ty * char_w + tx] = bbox_pixels[cy * bw + cx]
            pixels = padded
        else:
            pixels = [PALETTE_TO_GRAY.get(p, -1) for p in raw]

        templates[char] = {"pixels": pixels}

    return templates, char_w, char_h


def load_screen_templates() -> tuple[dict[str, dict], int, int]:
    """chars_out/templates_new.jsonからスクショテンプレートを読み込み、背景を透明化"""
    with open(CHARS_OUT / "templates_new.json", encoding="utf-8") as f:
        data = json.load(f)
    # 背景色の輝度帯を-1に置換
    for char, tpl in data["templates"].items():
        tpl["pixels"] = [
            -1 if NARROW_BG_MIN <= p <= NARROW_BG_MAX else p
            for p in tpl["pixels"]
        ]
    return data["templates"], data["meta"]["char_width"], data["meta"]["char_height"]


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    # 1. charmap解析
    char_to_idx = parse_charmap(CHARMAP_PATH)
    print(f"charmap: {len(char_to_idx)} chars")

    # 2. pretフォント抽出
    # normal/male/female: 16列 16x16セル、bbox→10x12
    # bold/small/tall: UI設定に従う
    VARIANT_SETTINGS = {
        "normal":  {"grid_cols": 16, "cell_w": 16, "cell_h": 16, "offset_x": 0, "offset_y": 0, "char_w": 10, "char_h": 12, "auto_bbox": True},
        "male":    {"grid_cols": 16, "cell_w": 16, "cell_h": 16, "offset_x": 0, "offset_y": 0, "char_w": 10, "char_h": 12, "auto_bbox": True},
        "female":  {"grid_cols": 16, "cell_w": 16, "cell_h": 16, "offset_x": 0, "offset_y": 0, "char_w": 10, "char_h": 12, "auto_bbox": True},
        "bold":    {"grid_cols": 32, "cell_w": 8, "cell_h": 16, "offset_x": 0, "offset_y": 4, "char_w": 8, "char_h": 12, "auto_bbox": False},
        "small":   {"grid_cols": 32, "cell_w": 8, "cell_h": 16, "offset_x": 0, "offset_y": 2, "char_w": 8, "char_h": 10, "auto_bbox": False},
        "tall":    {"grid_cols": 32, "cell_w": 8, "cell_h": 16, "offset_x": 0, "offset_y": 0, "char_w": 8, "char_h": 12, "auto_bbox": False},
    }
    pret_variants = {}
    pret_sizes = {}
    for name, path in FONT_VARIANTS.items():
        s = VARIANT_SETTINGS[name]
        tpl, out_w, out_h = extract_pret_variant(
            path, char_to_idx,
            grid_cols=s["grid_cols"], cell_w=s["cell_w"], cell_h=s["cell_h"],
            offset_x=s["offset_x"], offset_y=s["offset_y"],
            char_w=s["char_w"], char_h=s["char_h"],
            auto_bbox=s["auto_bbox"],
        )
        pret_variants[name] = tpl
        pret_sizes[name] = (out_w, out_h)
        print(f"pret {name}: {len(tpl)} chars ({out_w}x{out_h})")

    # 3. 統合JSON出力（narrowは廃止、tallで代替）
    output = {
        "meta": {
            "variants": list(FONT_VARIANTS.keys()),
            "source": "pret_fonts",
        },
        "variant_meta": {
            name: {"char_width": pret_sizes[name][0], "char_height": pret_sizes[name][1],
                   "source": f"japanese_{name}.png"} for name in FONT_VARIANTS
        },
        "variants": pret_variants,
        # デフォルト = tall
        "templates": pret_variants.get("tall", {}),
    }

    # 統計
    all_chars = set()
    for name, tpl in output["variants"].items():
        all_chars.update(tpl.keys())

    print(f"\n--- Summary ---")
    print(f"Total unique chars: {len(all_chars)}")
    for name, tpl in output["variants"].items():
        meta = output["variant_meta"][name]
        print(f"  {name}: {len(tpl)} chars @ {meta['char_width']}x{meta['char_height']}")

    # 書き出し
    OUTPUT_PATH.write_text(
        json.dumps(output, ensure_ascii=False),
        encoding="utf-8",
    )
    size_mb = OUTPUT_PATH.stat().st_size / 1024 / 1024
    print(f"\nSaved: {OUTPUT_PATH} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
