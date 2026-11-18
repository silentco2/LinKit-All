# Final kit generator. Run from brand/concepts:
#   uv run --no-project --with fonttools --with brotli --with shapely python build_final.py
import math, os
from shapely.geometry import LineString, box
from shapely.ops import unary_union
from shapely import affinity
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

OUT = ".."
BLUE, PAPER, INK = "#2c43a6", "#fbfaf7", "#1f1d1a"
DBLUE, DINK_BG, DTEXT = "#9dadf5", "#191816", "#efebe3"

def fmt(v):
    s = f"{v:.2f}".rstrip("0").rstrip("."); return "0" if s == "-0" else s
def ring(c):
    p = list(c)[:-1]; return "M" + " L".join(f"{fmt(x)} {fmt(y)}" for x, y in p) + " Z"
def geom_d(g):
    ps = [g] if g.geom_type == "Polygon" else list(g.geoms)
    o = []
    for p in ps:
        o.append(ring(p.exterior.coords)); o += [ring(i.coords) for i in p.interiors]
    return " ".join(o)
def band(p0, p1, w, clip=None):
    g = LineString([p0, p1]).buffer(w / 2, cap_style=2)
    return g.intersection(clip) if clip else g
def rrect(x, y, w, h, r):
    return (f"M{fmt(x+r)} {fmt(y)} H{fmt(x+w-r)} A{r} {r} 0 0 1 {fmt(x+w)} {fmt(y+r)} V{fmt(y+h-r)} A{r} {r} 0 0 1 {fmt(x+w-r)} {fmt(y+h)} "
            f"H{fmt(x+r)} A{r} {r} 0 0 1 {fmt(x)} {fmt(y+h-r)} V{fmt(y+r)} A{r} {r} 0 0 1 {fmt(x+r)} {fmt(y)} Z")

def lk(W, top, bot, xh, gap, arm_len, jdy, rnd, cy=128):
    l = box(0, top, W, bot)
    sx = W + gap
    stem = box(sx, top, sx + W, bot)
    J = (sx + W + 6, bot - jdy); t = W * 0.88
    arm = band(J, (J[0] + arm_len, J[1] - arm_len), t, box(0, xh, 400, bot))
    leg = band(J, (J[0] + arm_len, J[1] + arm_len), t, box(0, 0, 400, bot))
    bridge = box(sx + W - 2, J[1] - t / 2, J[0] + 3, J[1] + t / 2)
    g = unary_union([l, stem, arm, leg, bridge])
    g = g.buffer(-rnd, join_style=1, quad_segs=8).buffer(rnd, join_style=1, quad_segs=8)   # round convex
    g = g.buffer(rnd, join_style=1, quad_segs=8).buffer(-rnd, join_style=1, quad_segs=8)   # round concave
    minx, miny, maxx, maxy = g.bounds
    return affinity.translate(g, 128 - (minx + maxx) / 2, cy - (miny + maxy) / 2)

def symbol_d(small=False):
    if small:  # no ring, thicker letters, big tile
        g = lk(34, 0, 120, 28, 20, 56, 38, 3, cy=128)
        g = affinity.translate(g, 0, 0)
        return rrect(8, 8, 240, 240, 56) + " " + geom_d(g), False
    g = lk(25, 80, 176, 106 - 80, 22, 64, 32, 2.5)
    # optical: shift up ~1.5% (centre slightly above geometric)
    g = affinity.translate(g, 0, -2)
    return rrect(24, 24, 208, 208, 52) + " " + rrect(35, 35, 186, 186, 42) + " " + rrect(46, 46, 164, 164, 31) + " " + geom_d(g), True

def sym_g(fill, small=False):
    d, tilt = symbol_d(small)
    t = ' transform="rotate(-3 128 128)"' if tilt else ""
    return f'<g{t}><path fill="{fill}" fill-rule="evenodd" d="{d}"/></g>'

# wordmark
f = instantiateVariableFont(TTFont(r"D:\LinKit All\landing\fonts\ibm-plex-sans-latin-wght-normal.woff2"), {"wght": 500})
gs = f.getGlyphSet(); cmap = f.getBestCmap()
def word(t, size, x0, base, track=0):
    s = size / 1000; x = x0; out = []
    for ch in t:
        g = gs[cmap[ord(ch)]]; pen = SVGPathPen(gs, lambda v: fmt(v))
        g.draw(TransformPen(pen, (s, 0, 0, -s, x, base))); c = pen.getCommands()
        if c: out.append(c)
        x += g.width * s + track
    return " ".join(out), x

def svg(vb_w, vb_h, title, body, h=None):
    hh = f' height="{h}"' if h else ""
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w} {vb_h}"{hh} role="img"><title>{title}</title>{body}</svg>\n'

def horizontal(sfill, wfill):
    size, gap = 150, 44
    d, x = word("LinKit All", size, 256 + gap, 128 + 0.698 * size / 2, -1.5)
    return svg(int(math.ceil(x)) + 8, 256, "LinKit All", sym_g(sfill) + f'<path fill="{wfill}" d="{d}"/>', 256)

def stacked(sfill, wfill):
    size = 112
    d0, w = word("LinKit All", size, 0, 0, -1.2)
    W = int(math.ceil(max(w, 256))) + 16
    d, _ = word("LinKit All", size, (W - w) / 2, 256 + 40 + 0.698 * size, -1.2)
    sym = f'<g transform="translate({fmt((W-256)/2)} 0)">{sym_g(sfill)}</g>'
    H = int(256 + 40 + 0.698 * size + 0.25 * size) + 8
    return svg(W, H, "LinKit All", sym + f'<path fill="{wfill}" d="{d}"/>')

def w(name, s):
    open(os.path.join(OUT, name), "w", encoding="utf-8").write(s)
T = "LinKit All"
w("logo-symbol.svg", svg(256, 256, T, sym_g(BLUE), 256))
w("logo-symbol-black.svg", svg(256, 256, T, sym_g("#000000"), 256))
w("logo-symbol-white.svg", svg(256, 256, T, sym_g("#ffffff"), 256))
w("logo-symbol-dark.svg", svg(256, 256, T, sym_g(DBLUE), 256))
w("logo-symbol-small.svg", svg(256, 256, T, sym_g(BLUE, True), 256))
w("logo-horizontal.svg", horizontal(BLUE, INK))
w("logo-horizontal-dark.svg", horizontal(DBLUE, DTEXT))
w("logo-horizontal-black.svg", horizontal("#000000", "#000000"))
w("logo-stacked.svg", stacked(BLUE, INK))
print("ok")
