import random

SYM = {
    "k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟",
    "K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "P": "♙",
}

KNIGHT_D = ((1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2))
KING_D = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))
DIAG = ((1, 1), (1, -1), (-1, 1), (-1, -1))


def start_board():
    b = [["" for _ in range(8)] for _ in range(8)]
    back = "rnbqkbnr"
    for c in range(8):
        b[0][c] = back[c]
        b[1][c] = "p"
        b[6][c] = "P"
        b[7][c] = back[c].upper()
    return b


def render(b, selected=None, dests=None):
    lines = ["      a   b   c   d   e   f   g   h "]
    for r in range(8):
        cells = [f" {8 - r} |"]
        for c in range(8):
            p = b[r][c]
            sym = SYM.get(p, "·")
            if (r, c) == selected:
                s = f"‹{sym}"
            elif dests and (r, c) in dests:
                s = f"*{sym}"
            else:
                s = f" {sym}"
            cells.append(s.rjust(3))
        cells.append(f"| {8 - r}")
        lines.append(" ".join(cells))
    lines.append("      a   b   c   d   e   f   g   h ")
    return "\n".join(lines)


def pawn_moves(b, r, c, color, en_passant=None):
    d = -1 if color == "w" else 1
    start = 6 if color == "w" else 1
    moves = []
    rr = r + d
    if 0 <= rr < 8 and not b[rr][c]:
        moves.append((r, c, rr, c))
        if r == start and not b[r + 2 * d][c]:
            moves.append((r, c, r + 2 * d, c))
    for dc in (-1, 1):
        cc = c + dc
        if 0 <= cc < 8 and 0 <= rr < 8:
            tgt = b[rr][cc]
            if tgt and tgt.isupper() != (color == "w"):
                moves.append((r, c, rr, cc))
            if en_passant and (rr, cc) == en_passant:
                moves.append((r, c, rr, cc))
    return moves


def slide_moves(b, r, c, directions):
    moves = []
    me = b[r][c]
    for dr, dc in directions:
        rr, cc = r + dr, c + dc
        while 0 <= rr < 8 and 0 <= cc < 8:
            tgt = b[rr][cc]
            if not tgt:
                moves.append((r, c, rr, cc))
            else:
                if tgt.isupper() != me.isupper():
                    moves.append((r, c, rr, cc))
                break
            rr += dr
            cc += dc
    return moves


def castle_moves(b, r, c, color, castling):
    if color == "w" and r != 7 or color == "b" and r != 0:
        return []
    moves = []
    if color == "w":
        if castling and "K" in castling and b[7][7] == "R" and not b[7][5] and not b[7][6]:
            if not is_attacked(b, (7, 4), "b") and not is_attacked(b, (7, 5), "b") and not is_attacked(b, (7, 6), "b"):
                moves.append((7, 4, 7, 6))
        if castling and "Q" in castling and b[7][0] == "R" and not b[7][1] and not b[7][2] and not b[7][3]:
            if not is_attacked(b, (7, 4), "b") and not is_attacked(b, (7, 3), "b") and not is_attacked(b, (7, 2), "b"):
                moves.append((7, 4, 7, 2))
    else:
        if castling and "k" in castling and b[0][7] == "r" and not b[0][5] and not b[0][6]:
            if not is_attacked(b, (0, 4), "w") and not is_attacked(b, (0, 5), "w") and not is_attacked(b, (0, 6), "w"):
                moves.append((0, 4, 0, 6))
        if castling and "q" in castling and b[0][0] == "r" and not b[0][1] and not b[0][2] and not b[0][3]:
            if not is_attacked(b, (0, 4), "w") and not is_attacked(b, (0, 3), "w") and not is_attacked(b, (0, 2), "w"):
                moves.append((0, 4, 0, 2))
    return moves


def piece_moves(b, r, c, color, en_passant=None, castling=""):
    p = b[r][c]
    if p.lower() == "p":
        return pawn_moves(b, r, c, color, en_passant)
    if p.lower() == "n":
        out = []
        for dr, dc in KNIGHT_D:
            rr, cc = r + dr, c + dc
            if 0 <= rr < 8 and 0 <= cc < 8:
                tgt = b[rr][cc]
                if not tgt or tgt.isupper() != p.isupper():
                    out.append((r, c, rr, cc))
        return out
    if p.lower() == "k":
        out = []
        for dr, dc in KING_D:
            rr, cc = r + dr, c + dc
            if 0 <= rr < 8 and 0 <= cc < 8:
                tgt = b[rr][cc]
                if not tgt or tgt.isupper() != p.isupper():
                    out.append((r, c, rr, cc))
        return out + castle_moves(b, r, c, color, castling)
    if p in "Rr":
        return slide_moves(b, r, c, ORTHO)
    if p in "Bb":
        return slide_moves(b, r, c, DIAG)
    return slide_moves(b, r, c, ORTHO + DIAG)


def gen_pseudo(b, color, en_passant=None, castling=""):
    moves = []
    for r in range(8):
        for c in range(8):
            p = b[r][c]
            if not p:
                continue
            if p.isupper() != (color == "w"):
                continue
            moves += piece_moves(b, r, c, color, en_passant, castling)
    return moves


def is_attacked(b, sq, by_color):
    r, c = sq
    me = "w"
    d = 1 if by_color == "b" else -1
    for dc in (-1, 1):
        cc = c + dc
        rr = r + d
        if 0 <= rr < 8 and 0 <= cc < 8:
            tgt = b[rr][cc]
            if tgt and tgt == ("P" if by_color == "w" else "p"):
                return True
    for dr, dc in KNIGHT_D:
        rr, cc = r + dr, c + dc
        if 0 <= rr < 8 and 0 <= cc < 8:
            tgt = b[rr][cc]
            if tgt and tgt.lower() == "n" and tgt.isupper() == (by_color == "w"):
                return True
    for dr, dc in KING_D:
        rr, cc = r + dr, c + dc
        if 0 <= rr < 8 and 0 <= cc < 8:
            tgt = b[rr][cc]
            if tgt and tgt.lower() == "k" and tgt.isupper() == (by_color == "w"):
                return True
    for dr, dc in ORTHO + DIAG:
        rr, cc = r + dr, c + dc
        orthogonal = (dr, dc) in ORTHO
        while 0 <= rr < 8 and 0 <= cc < 8:
            tgt = b[rr][cc]
            if tgt:
                if tgt.isupper() == (by_color == "w"):
                    pl = tgt.lower()
                    if orthogonal and pl in "rq":
                        return True
                    if not orthogonal and pl in "bq":
                        return True
                break
            rr += dr
            cc += dc
    return False


def find_king(b, color):
    k = "K" if color == "w" else "k"
    for r in range(8):
        for c in range(8):
            if b[r][c] == k:
                return (r, c)
    return None


def in_check(b, color):
    k = find_king(b, color)
    if k is None:
        return False
    return is_attacked(b, k, "b" if color == "w" else "w")


def apply_move(b, fr, to, en_passant=None, castling="KQkq"):
    fr_r, fr_c = fr
    to_r, to_c = to
    nb = [row[:] for row in b]
    piece = nb[fr_r][fr_c]
    ep2 = None
    if piece.lower() == "p" and to == en_passant:
        nb[fr_r][to_c] = ""
    nb[to_r][to_c] = piece
    nb[fr_r][fr_c] = ""
    if piece.lower() == "p" and abs(to_r - fr_r) == 2:
        ep2 = ((fr_r + to_r) // 2, fr_c)
    if piece.lower() == "k" and abs(to_c - fr_c) == 2:
        if to_c == 6:
            nb[fr_r][5] = nb[fr_r][7]
            nb[fr_r][7] = ""
        else:
            nb[fr_r][3] = nb[fr_r][0]
            nb[fr_r][0] = ""
    castling2 = update_castling(b, fr, to, castling)
    return nb, ep2, castling2


CASTLE_FLAGS = {(7, 0): "Q", (7, 7): "K", (0, 0): "q", (0, 7): "k"}


def update_castling(b, fr, to, castling):
    c = set(castling)
    piece = b[fr[0]][fr[1]]
    if piece.lower() == "k":
        if piece.isupper():
            c.discard("K")
            c.discard("Q")
        else:
            c.discard("k")
            c.discard("q")
    if fr in CASTLE_FLAGS:
        c.discard(CASTLE_FLAGS[fr])
    if to in CASTLE_FLAGS and b[to[0]][to[1]] in "rR":
        c.discard(CASTLE_FLAGS[to])
    return "".join(ch for ch in "KQkq" if ch in c)


def legal_moves(b, color, en_passant=None, castling="KQkq"):
    out = []
    for fr_r, fr_c, to_r, to_c in gen_pseudo(b, color, en_passant, castling):
        nb, _, ncastling = apply_move(b, (fr_r, fr_c), (to_r, to_c), en_passant, castling)
        if not in_check(nb, color):
            out.append((fr_r, fr_c, to_r, to_c))
    return out


def status(b, color, en_passant=None, castling="KQkq"):
    moves = legal_moves(b, color, en_passant, castling)
    if moves:
        return "ok", moves
    if in_check(b, color):
        return "checkmate", []
    return "stalemate", []


def dests_for(b, fr, color, en_passant=None, castling="KQkq"):
    out = set()
    for fr_r, fr_c, to_r, to_c in legal_moves(b, color, en_passant, castling):
        if (fr_r, fr_c) == fr:
            out.add((to_r, to_c))
    return out


def promote(b, color):
    row = 0 if color == "w" else 7
    for c in range(8):
        if b[row][c] == ("P" if color == "w" else "p"):
            b[row][c] = ("Q" if color == "w" else "q")


def bot_move(b, en_passant=None, castling="KQkq"):
    moves = legal_moves(b, "b", en_passant, castling)
    if not moves:
        return None
    captures = [m for m in moves if b[m[2]][m[3]]]
    pool = captures if captures else moves
    return random.choice(pool)


def is_draw(b, color):
    white = sum(1 for row in b for p in row if p and p.isupper())
    black = sum(1 for row in b for p in row if p and p.islower())
    if white <= 1 and black <= 1:
        return True
    return False