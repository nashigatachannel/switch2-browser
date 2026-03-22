"""
generate_templates.py

charmap.txt をパースして japanese_normal.png から各文字セルを切り出し、
グレースケール化して templates.json に書き出す。

NOTE: charmap.txt は2つのエンコーディング体系を混在させている。
- ラテン文字セクション（ファイル先頭）: hex値 = PNGセルインデックス（直接対応）
- 日本語セクション（@ Hiragana 以降）: PNGセルインデックス = hex値 + 1
  （ゲームROMエンコーディングとフォントPNGの配置に +1 のずれがある）
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from PIL import Image

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
FONTS_DIR = Path(__file__).parent
CHARMAP_PATH = FONTS_DIR / "charmap.txt"
OUTPUT_PATH = FONTS_DIR.parent / "templates.json"

# 3フォントバリアント
FONT_VARIANTS = {
    "normal": FONTS_DIR / "japanese_normal.png",
    "male": FONTS_DIR / "japanese_male.png",
    "female": FONTS_DIR / "japanese_female.png",
}

CELL_W = 16    # セル幅（文字10px + 空白6px）
CELL_H = 16    # セル高さ（文字12px + 空白4px）
CHAR_W = 10    # 文字の実際の幅
CHAR_H = 12    # 文字の実際の高さ
GRID_COLS = 16 # 256 / 16

# パレットインデックス → グレースケール値 (-1 = 背景、マッチング時に無視)
PALETTE_TO_GRAY: dict[int, int] = {
    0: -1,    # 背景 → マッチング対象外
    1: 0,     # アウトライン (黒)
    2: 64,    # 影 (暗めグレー)
    3: 192,   # 文字本体 (明るいグレー)
}

# 日本語セクションのマーカー（このセクション以降はPNGインデックスに +1 オフセット）
JAPANESE_SECTION_MARKERS = {"@ Hiragana", "@ Katakana", "@ Japanese punctuation"}


# ---------------------------------------------------------------------------
# charmap パーサ
# ---------------------------------------------------------------------------
def parse_charmap(charmap_path: Path) -> dict[str, int]:
    """
    1文字 = 1バイト(2桁 hex)の行のみを抽出して {文字: PNGセルインデックス} を返す。

    対象行の形式: 'X' = HH  (HH は2桁の16進数、スペースなし)
    複数バイト定義 (HH HH ...) やコントロールコード行 (FD xx) はスキップ。
    @コメント行・空行もスキップ。

    日本語セクション（@ Hiragana 以降）は png_index = hex_val + 1 として記録する。
    """
    char_to_png_index: dict[str, int] = {}

    # 1文字シングルクォートで囲まれた文字 + スペース + = + スペース + 2桁hex (行末)
    single_char_pattern = re.compile(
        r"^'(.)'(?:\s+)?=\s+([0-9A-Fa-f]{2})\s*$"
    )

    is_japanese_section = False

    with charmap_path.open(encoding="utf-8") as fh:
        for raw_line in fh:
            # 行番号プレフィックス "  N→" を除去
            line = re.sub(r"^\s*\d+→", "", raw_line).strip()

            # @コメント行 → セクション判定してスキップ
            if line.startswith("@"):
                if any(marker in line for marker in JAPANESE_SECTION_MARKERS):
                    is_japanese_section = True
                continue

            # 空行はスキップ
            if not line:
                continue

            match = single_char_pattern.match(line)
            if match:
                char = match.group(1)
                hex_val = int(match.group(2), 16)
                png_index = hex_val
                # 同一文字が複数定義されている場合は先勝ち
                if char not in char_to_png_index:
                    char_to_png_index[char] = png_index

    return char_to_png_index


# ---------------------------------------------------------------------------
# 対象文字フィルタ
# ---------------------------------------------------------------------------
def is_target_char(char: str) -> bool:
    """ひらがな・カタカナ・記号・ラテン文字(A-Z, a-z, 0-9)・よく使う記号のみ抽出。"""
    cp = ord(char)
    # ひらがな U+3041–U+3096
    if 0x3041 <= cp <= 0x3096:
        return True
    # カタカナ U+30A0–U+30FF
    if 0x30A0 <= cp <= 0x30FF:
        return True
    # ASCII英数字・一般記号
    if char.isalnum() and cp < 0x80:
        return True
    # 記号セット（ゲーム内で使われる可能性が高いもの）
    allowed_symbols = set("!?.-,/…'\"()&+=%<>:;·×¥♂♀　！？。ー‥▶")
    if char in allowed_symbols:
        return True
    return False


# ---------------------------------------------------------------------------
# セル切り出し＆グレースケール変換
# ---------------------------------------------------------------------------
def extract_cell_pixels(
    palette_img: Image.Image,
    hex_val: int,
) -> list[int]:
    """
    palette_img からhex_valに対応するセルを切り出し、
    文字部分(CHAR_W x CHAR_H)のグレースケール値を返す。
    """
    col = hex_val % GRID_COLS
    row = hex_val // GRID_COLS

    # セル左上座標（16pxグリッド）
    x0 = col * CELL_W
    y0 = row * CELL_H
    # 文字部分だけ切り出し（セル内の左上CHAR_W x CHAR_H）
    x1 = x0 + CHAR_W
    y1 = y0 + CHAR_H

    cell = palette_img.crop((x0, y0, x1, y1))
    raw_pixels: list[int] = list(cell.tobytes())

    gray_pixels = [
        PALETTE_TO_GRAY.get(p, 255) for p in raw_pixels
    ]
    return gray_pixels


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def extract_variant(
    variant_name: str,
    png_path: Path,
    char_to_png_index: dict[str, int],
) -> dict[str, dict]:
    """1フォントバリアントから全文字テンプレートを抽出する。"""
    print(f"PNG 読み込み中: {png_path}")
    palette_img = Image.open(png_path)
    if palette_img.mode != "P":
        print(f"  警告: 想定外のモード {palette_img.mode}、処理を続行します")

    templates: dict[str, dict] = {}
    skipped_chars: list[str] = []

    for char, png_index in char_to_png_index.items():
        if not is_target_char(char):
            skipped_chars.append(char)
            continue

        row = png_index // GRID_COLS
        if (row + 1) * CELL_H > palette_img.height:
            continue

        pixels = extract_cell_pixels(palette_img, png_index)
        templates[char] = {
            "pixels": pixels,
            "w": CHAR_W,
            "h": CHAR_H,
        }

    print(f"  {variant_name}: {len(templates)} 文字抽出")
    return templates


def main() -> None:
    print(f"charmap パース中: {CHARMAP_PATH}")
    char_to_png_index = parse_charmap(CHARMAP_PATH)
    print(f"  パース結果: {len(char_to_png_index)} 文字")

    all_variants: dict[str, dict[str, dict]] = {}
    for variant_name, png_path in FONT_VARIANTS.items():
        all_variants[variant_name] = extract_variant(
            variant_name, png_path, char_to_png_index
        )

    output_data = {
        "meta": {
            "char_width": CHAR_W,
            "char_height": CHAR_H,
            "variants": list(FONT_VARIANTS.keys()),
            "source": list(FONT_VARIANTS.values()).__str__(),
        },
        "templates": all_variants["normal"],  # デフォルトはnormal
        "variants": all_variants,             # 全バリアント
    }

    total = sum(len(v) for v in all_variants.values())
    print(f"\nJSON 書き出し中: {OUTPUT_PATH}")
    print(f"  合計: {total} テンプレート ({len(all_variants)} variants)")
    OUTPUT_PATH.write_text(
        json.dumps(output_data, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"完了: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
