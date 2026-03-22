"""
ゲーム画面のキャラクタテーブルを1文字ずつに分割。
画像ごとにグループ構造を定義して正確に分割。
"""
from PIL import Image, ImageDraw
import numpy as np
import os, json

OUT_DIR = "chars_out"
os.makedirs(OUT_DIR, exist_ok=True)

def to_gray(img):
    arr = np.array(img.convert('RGB'))
    return 0.299 * arr[:,:,0] + 0.587 * arr[:,:,1] + 0.114 * arr[:,:,2]

def find_rows(gray, threshold=175):
    """行の境界を検出"""
    binary = (gray > threshold).astype(int)
    h_proj = binary.sum(axis=1)
    rows = []
    in_char = False
    start = 0
    for y in range(gray.shape[0]):
        if h_proj[y] >= 2:
            if not in_char:
                start = y
                in_char = True
        else:
            if in_char:
                if y - start >= 10:
                    rows.append((start, y - 1))
                in_char = False
    if in_char and gray.shape[0] - start >= 10:
        rows.append((start, gray.shape[0] - 1))
    return rows

def find_char_extent(gray_row, threshold=175):
    """行の文字がある左端と右端を検出"""
    binary = (gray_row > threshold).astype(int)
    v_proj = binary.sum(axis=0)
    left = 0
    right = gray_row.shape[1] - 1
    for x in range(gray_row.shape[1]):
        if v_proj[x] > 0:
            left = x
            break
    for x in range(gray_row.shape[1] - 1, -1, -1):
        if v_proj[x] > 0:
            right = x
            break
    return left, right

def find_group_boundaries(gray_row, n_groups, threshold=175):
    """行内のn_groups個のグループの境界を検出。大きなギャップで分割"""
    binary = (gray_row > threshold).astype(int)
    v_proj = binary.sum(axis=0)
    w = gray_row.shape[1]

    # 連続する空白区間を全て検出
    gaps = []
    in_gap = False
    start = 0
    for x in range(w):
        if v_proj[x] == 0:
            if not in_gap:
                start = x
                in_gap = True
        else:
            if in_gap:
                gaps.append((start, x - 1, x - start))
                in_gap = False

    if n_groups <= 1:
        # 1グループ = 行全体
        left, right = find_char_extent(gray_row, threshold)
        return [(left, right)]

    # 最低幅でフィルタ（文字間ギャップ3-5pxより大きいもの）
    big_gaps = [g for g in gaps if g[2] >= 10]

    if len(big_gaps) < n_groups - 1:
        # 足りなければ全ギャップから幅順で補充
        big_gaps = sorted(gaps, key=lambda g: g[2], reverse=True)[:n_groups - 1]
    elif len(big_gaps) > n_groups - 1:
        # 多すぎる場合: 画像を等分に近く分割するn_groups-1個を選ぶ
        # 理想的な分割位置
        left, right = find_char_extent(gray_row, threshold)
        total_w = right - left + 1
        ideal_positions = [(left + total_w * (i + 1) / n_groups) for i in range(n_groups - 1)]
        # 各理想位置に最も近いギャップを選択（重複なし）
        used = set()
        selected = []
        for ideal_x in ideal_positions:
            best = None
            best_dist = float('inf')
            for gi, g in enumerate(big_gaps):
                if gi in used:
                    continue
                mid = (g[0] + g[1]) / 2
                dist = abs(mid - ideal_x)
                if dist < best_dist:
                    best_dist = dist
                    best = gi
            if best is not None:
                used.add(best)
                selected.append(big_gaps[best])
        big_gaps = selected

    split_gaps = sorted(big_gaps[:n_groups - 1], key=lambda g: g[0])

    # グループの範囲を決定
    groups = []
    prev_end = 0
    for gap in split_gaps:
        # グループの文字範囲を検出
        left, right = find_char_extent(gray_row[:, prev_end:gap[0]], threshold)
        groups.append((prev_end + left, prev_end + right))
        prev_end = gap[1] + 1

    # 最後のグループ
    left, right = find_char_extent(gray_row[:, prev_end:], threshold)
    groups.append((prev_end + left, prev_end + right))

    return groups

def split_group_evenly(img, x0, x1, y0, y1, n_chars):
    """指定範囲をn_chars等分"""
    gw = x1 - x0 + 1
    cell_w = gw / n_chars
    cells = []
    for i in range(n_chars):
        cx0 = x0 + round(i * cell_w)
        cx1 = x0 + round((i + 1) * cell_w)
        crop = img.crop((cx0, y0, cx1, y1 + 1))
        cells.append(crop)
    return cells


def process_table(path, row_defs):
    """
    row_defs: list of lists of strings
    Each row = [group1_chars, group2_chars, ...]
    """
    img = Image.open(path).convert('RGB')
    gray = to_gray(img)
    h, w = gray.shape
    rows = find_rows(gray)
    print(f"\n{path} ({w}x{h}), {len(rows)} rows detected")

    all_cells = []  # [(char, image, row, col)]

    for ri, (ry0, ry1) in enumerate(rows):
        if ri >= len(row_defs):
            break
        groups_def = row_defs[ri]
        n_groups = len(groups_def)
        rh = ry1 - ry0 + 1

        # グループ境界を検出
        group_bounds = find_group_boundaries(gray[ry0:ry1+1, :], n_groups)

        col = 0
        for gi, chars in enumerate(groups_def):
            if gi >= len(group_bounds):
                print(f"  Row {ri}: group {gi} has no boundary!")
                break

            gx0, gx1 = group_bounds[gi]
            cells = split_group_evenly(img, gx0, gx1, ry0, ry1, len(chars))

            for ci, cell in enumerate(cells):
                ch = chars[ci]
                if ch and ch != ' ':
                    all_cells.append((ch, cell, ri, col))
                col += 1

        total_chars = sum(len(g) for g in groups_def)
        print(f"  Row {ri} (y={ry0}-{ry1}): {total_chars} chars, {n_groups} groups")

    return all_cells


def make_preview(cells, row_defs, prefix):
    if not cells:
        return
    max_w = max(c[1].width for c in cells)
    max_h = max(c[1].height for c in cells)
    cw = max_w + 2
    ch = max_h + 2
    total_cols = max(sum(len(g) for g in row) for row in row_defs)
    n_rows = len(row_defs)

    pw = total_cols * (cw + 1) + 10
    ph = n_rows * (ch + 16) + 10
    preview = Image.new('RGB', (pw, ph), (10, 10, 30))
    draw = ImageDraw.Draw(preview)

    for char, cell_img, ri, ci in cells:
        px = 5 + ci * (cw + 1)
        py = 5 + ri * (ch + 16)
        ox = (cw - cell_img.width) // 2
        oy = (ch - cell_img.height) // 2
        preview.paste(cell_img, (px + ox, py + oy))
        draw.text((px + 2, py + ch + 1), char, fill=(200, 200, 200))

    out = os.path.join(OUT_DIR, f"{prefix}_preview.png")
    preview.save(out)
    print(f"  Preview: {out}")


def safe_filename(char):
    for bad, rep in [('/', '_sl'), ('\\', '_bs'), ('?', '_q'), ('!', '_ex'),
                     ('"', '_dq'), ("'", '_sq'), ('「', '_lb'), ('」', '_rb'),
                     ('&', '_am'), ('#', '_ha'), ('.', '_dt'), ('。', '_mr'),
                     ('゛', '_dk'), ('ー', '_br'), ('っ', '_ts'), ('□', '_bx'),
                     (' ', '_sp'), ('*', '_as')]:
        char = char.replace(bad, rep)
    return char


# ===== ひらがなテーブル =====
# 3グループ: 5文字 | 5文字 | 5-6文字
hiragana_rows = [
    ["あいうえお", "なにぬねの", "やゆよ！？□"],
    ["かきくけこ", "はひふへほ", "わをん゛。"],
    ["さしすせそ", "まみむめも", "ゃゅょっー"],
    ["たちつてと", "らりるれろ", "ぁぃぅぇぉ"],
]

# ===== カタカナテーブル =====
katakana_rows = [
    ["アイウエオ", "ナニヌネノ", "ヤユヨ！？□"],
    ["カキクケコ", "ハヒフヘホ", "ワヲン゛。"],
    ["サシスセソ", "マミムメモ", "ャュョッー"],
    ["タチツテト", "ラリルレロ", "ァィゥェォ"],
]

# ===== ABCテーブル =====
# 1グループ（ギャップなし）
abc_rows = [
    ["ABCDEFGHIJKLMNOPQRS"],
    ["TUVWXYZ 0123456789"],
    ["abcdefghijklmnopqrs"],
    ['tuvwxyz .""「」/&#'],
]

print("=" * 50)
print("Character Table Splitter v3")
print("=" * 50)

hira_cells = process_table("capture_hiragana.png", hiragana_rows)
kata_cells = process_table("screenshot.png", katakana_rows)
abc_cells = process_table("capture_abc.png", abc_rows)

make_preview(hira_cells, hiragana_rows, "hira")
make_preview(kata_cells, katakana_rows, "kata")
make_preview(abc_cells, abc_rows, "abc")

all_cells = hira_cells + kata_cells + abc_cells

# 個別PNG保存
for char, cell_img, ri, ci in all_cells:
    cell_img.save(os.path.join(OUT_DIR, f"{safe_filename(char)}.png"))

# テンプレートJSON生成
TARGET_W = 24
TARGET_H = 36
templates = {}
for char, cell_img, ri, ci in all_cells:
    resized = cell_img.resize((TARGET_W, TARGET_H), Image.NEAREST)
    gray_arr = np.array(resized.convert('L'))
    templates[char] = {"pixels": gray_arr.flatten().tolist()}

out_json = {
    "meta": {"char_width": TARGET_W, "char_height": TARGET_H, "source": "screen_capture_split_v3"},
    "templates": templates
}
with open(os.path.join(OUT_DIR, "templates_new.json"), "w", encoding="utf-8") as f:
    json.dump(out_json, f, ensure_ascii=False)

print(f"\nTotal: {len(templates)} chars → {OUT_DIR}/templates_new.json ({TARGET_W}x{TARGET_H})")
