# Builds concept symbols + lockups. Run: uv run --with fonttools --with brotli --with shapely python build.py <ver>
import sys, math
from shapely.geometry import Polygon, LineString, box
from shapely.ops import unary_union
from shapely import affinity
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
V = sys.argv[1] if len(sys.argv) > 1 else "v1"
INK = "#000"

def fmt(v): 
    s=f"{v:.2f}".rstrip('0').rstrip('.'); return "0" if s=="-0" else s
def ring(coords):
    pts=list(coords)[:-1]
    return "M"+" L".join(f"{fmt(x)} {fmt(y)}" for x,y in pts)+" Z"
def geom_d(g):
    polys=[g] if g.geom_type=="Polygon" else list(g.geoms)
    out=[]
    for p in polys:
        out.append(ring(p.exterior.coords))
        for i in p.interiors: out.append(ring(i.coords))
    return " ".join(out)
def band(p0,p1,w,clip=None):
    g=LineString([p0,p1]).buffer(w/2,cap_style=2)
    return g.intersection(clip) if clip else g
def rrect(x,y,w,h,r):
    return f"M{fmt(x+r)} {fmt(y)} H{fmt(x+w-r)} A{r} {r} 0 0 1 {fmt(x+w)} {fmt(y+r)} V{fmt(y+h-r)} A{r} {r} 0 0 1 {fmt(x+w-r)} {fmt(y+h)} H{fmt(x+r)} A{r} {r} 0 0 1 {fmt(x)} {fmt(y+h-r)} V{fmt(y+r)} A{r} {r} 0 0 1 {fmt(x+r)} {fmt(y)} Z"

# ---------- A: stamped tile ----------
def sym_a():
    W=25; top,bot,xh=80,176,106
    l=box(0,top,W,bot)
    sx=W+22
    stem=box(sx,top,sx+W,bot)
    J=(sx+W+6,144); t=W*0.88
    arm=band(J,(J[0]+64,J[1]-64),t,box(0,xh,400,bot))
    leg=band(J,(J[0]+64,J[1]+64),t,box(0,0,400,bot))
    bridge=box(sx+W-2,J[1]-t/2,J[0]+3,J[1]+t/2)
    k=unary_union([stem,arm,leg,bridge])
    glyphs=unary_union([l,k])
    minx,miny,maxx,maxy=glyphs.bounds
    glyphs=affinity.translate(glyphs,128-(minx+maxx)/2,128-(miny+maxy)/2)
    d=rrect(24,24,208,208,52)+" "+rrect(35,35,186,186,42)+" "+rrect(46,46,164,164,31)+" "+geom_d(glyphs)
    return f'<g transform="rotate(-3 128 128)"><path fill="{INK}" fill-rule="evenodd" d="{d}"/></g>'

# ---------- B: paperclip L ----------
def sym_b():
    # monoline L (stroke 26); the foot U-turns downward and doubles back under itself like paperclip wire
    dx,dy=-12.5,7
    def P(x,y): return f"{fmt(x+dx)} {fmt(y+dy)}"
    d=(f"M{P(71,40)} A13 13 0 0 1 {P(97,40)} V{fmt(124+dy)} A15 15 0 0 0 {P(112,139)} H{fmt(172+dx)} "
       f"A38 38 0 0 1 {P(172,215)} H{fmt(84+dx)} A13 13 0 0 1 {P(84,189)} H{fmt(172+dx)} "
       f"A12 12 0 0 0 {P(172,165)} H{fmt(112+dx)} A41 41 0 0 1 {P(71,124)} Z")
    return f'<path fill="{INK}" d="{d}"/>'

# ---------- C: folder-tab badge ----------
def sym_c():
    body=("M24 52 A24 24 0 0 1 48 28 H100 A16 16 0 0 1 116 44 V54 A16 16 0 0 0 132 70 H192 A40 40 0 0 1 232 110 V192 "
          "A40 40 0 0 1 192 232 H64 A40 40 0 0 1 24 192 Z")
    W=28
    stem=box(72,96,72+W,200)
    pts=[(116,166),(144,194),(200,122)]
    chk=LineString(pts).buffer(W/2,join_style=2,cap_style=2,mitre_limit=3)
    g=unary_union([stem,chk])
    minx,miny,maxx,maxy=g.bounds
    g=affinity.translate(g,128-(minx+maxx)/2,(150)-(miny+maxy)/2)
    return f'<path fill="{INK}" fill-rule="evenodd" d="{body} {geom_d(g)}"/>'

# ---------- wordmark ----------
f=TTFont(r"D:\LinKit All\landing\fonts\ibm-plex-sans-latin-wght-normal.woff2")
f=instantiateVariableFont(f,{"wght":500})
gs=f.getGlyphSet(); cmap=f.getBestCmap()
def word(t,size,x0,base,track=0):
    s=size/1000; x=x0; out=[]
    for ch in t:
        g=gs[cmap[ord(ch)]]
        pen=SVGPathPen(gs,lambda v:fmt(v))
        g.draw(TransformPen(pen,(s,0,0,-s,x,base))); c=pen.getCommands()
        if c: out.append(c)
        x+=g.width*s+track
    return " ".join(out),x
def lockup(sym,name,size=150,gap=44):
    base=128+0.698*size/2
    d,x=word("LinKit All",size,256+gap,base,track=-1.5)
    wm=f'<path fill="{INK}" d="{d}"/>'
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {int(math.ceil(x))+8} 256" height="256" role="img"><title>{name}</title><g id="symbol">{sym}</g><g id="wordmark">{wm}</g></svg>'
def symsvg(sym,name):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256" role="img"><title>{name}</title>{sym}</svg>'
for k,(fn,n) in {"a":(sym_a,"LinKit All stamped tile"),"b":(sym_b,"LinKit All paperclip L"),"c":(sym_c,"LinKit All folder-tab badge")}.items():
    s=fn()
    open(f"concept-{k}-{V}.svg","w").write(symsvg(s,n))
    open(f"concept-{k}-{V}-lockup.svg","w").write(lockup(s,n))
print("ok",V)
