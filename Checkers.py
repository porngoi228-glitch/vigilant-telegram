import random
import re

SIZE = 8


def off(r, c):
    return not (0 <= r < SIZE and 0 <= c < SIZE)


def other(color):
    return "b" if color == "w" else "w"


def is_king(piece):
    return bool(piece and piece.endswith("k"))


def piece_color(piece):
    return piece[0]


def forward(color):
    return 1 if color == "w" else -1


def promo_row(color):
    return SIZE - 1 if color == "w" else 0


def sq_index(name):
    name = name.strip().lower()
    if len(name) != 2:
        return None
    f, r = name[0], name[1]
    if f < "a" or f > "h" or r < "1" or r > "8":
        return None
    return int(r) - 1, ord(f) - ord("a")


def sq_name(r, c):
    return chr(ord("a") + c) + str(r + 1)


def start_board():
    b = [[None] * SIZE for _ in range(SIZE)]
    for r in range(3):
        for c in range(SIZE):
            if (r + c) % 2 == 1:
                b[r][c] = "w"
    for r in range(5, SIZE):
        for c in range(SIZE):
            if (r + c) % 2 == 1:
                b[r][c] = "b"
    return b


def piece_count(b, color):
    return sum(1 for r in range(SIZE) for c in range(SIZE)
               if b[r][c] is not None and piece_color(b[r][c]) == color)


def _capture_chain(b, color, kind, r, c, path, caps):
    results = []
    for dr in (-1, 1):
        for dc in (-1, 1):
            if kind == "king":
                sr, sc = r + dr, c + dc
                while not off(sr, sc) and b[sr][sc] is None:
                    sr += dr
                    sc += dc
                if off(sr, sc):
                    continue
                opp = b[sr][sc]
                if opp is None or piece_color(opp) == color:
                    continue
                lr, lc = sr + dr, sc + dc
                while not off(lr, lc) and b[lr][lc] is None:
                    b[sr][sc] = None
                    sub = _capture_chain(b, color, "king", lr, lc,
                                         path + [(lr, lc)], caps + [(sr, sc)])
                    b[sr][sc] = opp
                    if sub:
                        results.extend(sub)
                    else:
                        results.append((path + [(lr, lc)], caps + [(sr, sc)]))
                    lr += dr
                    lc += dc
            else:
                sr, sc = r + dr, c + dc
                if off(sr, sc):
                    continue
                opp = b[sr][sc]
                if opp is None or piece_color(opp) == color:
                    continue
                lr, lc = r + 2 * dr, c + 2 * dc
                if off(lr, lc) or b[lr][lc] is not None:
                    continue
                b[sr][sc] = None
                sub = _capture_chain(b, color, "man", lr, lc,
                                     path + [(lr, lc)], caps + [(sr, sc)])
                b[sr][sc] = opp
                if sub:
                    results.extend(sub)
                else:
                    results.append((path + [(lr, lc)], caps + [(sr, sc)]))
    return results


def _captured_between(b, a, z):
    dr = (z[0] - a[0]) // max(1, abs(z[0] - a[0]))
    dc = (z[1] - a[1]) // max(1, abs(z[1] - a[1]))
    rr, cc = a[0] + dr, a[1] + dc
    captured = []
    while (rr, cc) != z:
        if b[rr][cc] is not None:
            captured.append((rr, cc))
        rr += dr
        cc += dc
    return captured


def legal_moves(b, color):
    captures = []
    for r in range(SIZE):
        for c in range(SIZE):
            p = b[r][c]
            if p is None or piece_color(p) != color:
                continue
            kind = "king" if is_king(p) else "man"
            for path, caps in _capture_chain(b, color, kind, r, c, [(r, c)], []):
                land = path[-1]
                promote = kind == "man" and land[0] == promo_row(color)
                captures.append({
                    "squares": path,
                    "captured": caps,
                    "is_capture": True,
                    "promote": promote,
                })
    if captures:
        return captures
    quiet = []
    for r in range(SIZE):
        for c in range(SIZE):
            p = b[r][c]
            if p is None or piece_color(p) != color:
                continue
            if not is_king(p):
                fr = forward(color)
                for dr, dc in ((fr, -1), (fr, 1)):
                    rr, cc = r + dr, c + dc
                    if not off(rr, cc) and b[rr][cc] is None:
                        quiet.append({
                            "squares": [(r, c), (rr, cc)],
                            "captured": [],
                            "is_capture": False,
                            "promote": rr == promo_row(color),
                        })
            else:
                for dr, dc in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                    rr, cc = r + dr, c + dc
                    while not off(rr, cc) and b[rr][cc] is None:
                        quiet.append({
                            "squares": [(r, c), (rr, cc)],
                            "captured": [],
                            "is_capture": False,
                            "promote": False,
                        })
                        rr += dr
                        cc += dc
    return quiet


def apply_move(b, color, move):
    nb = [row[:] for row in b]
    start = move["squares"][0]
    kind = "king" if is_king(nb[start[0]][start[1]]) else "man"
    piece = nb[start[0]][start[1]]
    nb[start[0]][start[1]] = None
    for i in range(len(move["squares"]) - 1):
        a, z = move["squares"][i], move["squares"][i + 1]
        for mr, mc in _captured_between(nb, a, z):
            nb[mr][mc] = None
    land = move["squares"][-1]
    nb[land[0]][land[1]] = piece
    if kind == "man" and move["promote"]:
        nb[land[0]][land[1]] = "wk" if color == "w" else "bk"
    return nb


def parse_path(text):
    parts = [p for p in re.split(r"[\s\-–—:x×]+", text.strip().lower()) if p]
    squares = [sq_index(p) for p in parts]
    if len(squares) < 2 or any(s is None for s in squares):
        return None
    return squares


def user_move(b, color, path):
    for m in legal_moves(b, color):
        if m["squares"] == path:
            return m
    return None


def choose_move(b, color):
    moves = legal_moves(b, color)
    if not moves:
        return None
    best = None
    best_score = None
    random.shuffle(moves)
    for m in moves:
        nb = apply_move(b, color, m)
        opp = legal_moves(nb, other(color))
        opp_best = max((len(x["captured"]) for x in opp), default=0)
        score = len(m["captured"]) * 10 - opp_best * 6 + (5 if m["promote"] else 0)
        if best_score is None or score > best_score:
            best = m
            best_score = score
    return best


SYMBOLS = {
    "w": "⛀",
    "wk": "⛁",
    "b": "⛂",
    "bk": "⛃",
}


def render(b):
    lines = ["  a b c d e f g h"]
    for r in range(SIZE - 1, -1, -1):
        row = [str(r + 1)]
        for c in range(SIZE):
            row.append(SYMBOLS.get(b[r][c], "·"))
        lines.append(" ".join(row))
    lines.append("  a b c d e f g h")
    return "\n".join(lines)