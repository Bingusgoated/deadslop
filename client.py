"""DEADSLOP Panda3D client.   python client.py [wss://your-app.onrender.com/ws]"""
import json, math, os, queue, random, sys, threading
from panda3d.core import *
loadPrcFileData("", "window-title DEADSLOP\nwin-size 1280 720\nmultisamples 4\nframebuffer-multisample 1\n")
from direct.showbase.ShowBase import ShowBase
from direct.gui.DirectGui import *
from direct.gui.OnscreenText import OnscreenText
from websockets.sync.client import connect
from shared import *

DEFAULT_URL = "ws://localhost:10000/ws"   # <- put your Render URL here (wss://NAME.onrender.com/ws)


# ---------------------------------------------------------------- geometry
def _node(name, vd, tris):
    g = Geom(vd); g.addPrimitive(tris)
    gn = GeomNode(name); gn.addGeom(g)
    return NodePath(gn)


def make_box(sx, sy, sz, col):
    vd = GeomVertexData("b", GeomVertexFormat.getV3n3c4(), Geom.UHStatic)
    vw, nw, cw = (GeomVertexWriter(vd, n) for n in ("vertex", "normal", "color"))
    tris = GeomTriangles(Geom.UHStatic); hs = (sx / 2, sy / 2, sz / 2); i = 0
    faces = [((1, 0, 0), (0, 1, 0), (0, 0, 1)), ((-1, 0, 0), (0, 0, 1), (0, 1, 0)),
             ((0, 1, 0), (0, 0, 1), (1, 0, 0)), ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
             ((0, 0, 1), (1, 0, 0), (0, 1, 0)), ((0, 0, -1), (0, 1, 0), (1, 0, 0))]
    for n, u, v in faces:
        for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            vw.addData3(*[(n[k] + su * u[k] + sv * v[k]) * hs[k] for k in range(3)])
            nw.addData3(*n); cw.addData4(col[0], col[1], col[2], 1)
        tris.addVertices(i, i + 1, i + 2); tris.addVertices(i, i + 2, i + 3); i += 4
    return _node("box", vd, tris)


def make_sphere(r, col, seg=12):
    vd = GeomVertexData("s", GeomVertexFormat.getV3n3c4(), Geom.UHStatic)
    vw, nw, cw = (GeomVertexWriter(vd, n) for n in ("vertex", "normal", "color"))
    tris = GeomTriangles(Geom.UHStatic); n2 = seg * 2
    for i in range(seg + 1):
        ph = math.pi * i / seg
        for j in range(n2 + 1):
            th = 2 * math.pi * j / n2
            nx, ny, nz = math.sin(ph) * math.cos(th), math.sin(ph) * math.sin(th), math.cos(ph)
            vw.addData3(nx * r, ny * r, nz * r); nw.addData3(nx, ny, nz); cw.addData4(col[0], col[1], col[2], 1)
    for i in range(seg):
        for j in range(n2):
            a = i * (n2 + 1) + j; b = a + n2 + 1
            tris.addVertices(a, b, a + 1); tris.addVertices(a + 1, b, b + 1)
    return _node("sph", vd, tris)


def make_bar(width, col):
    root = NodePath("bar")
    cm = CardMaker("bg"); cm.setFrame(-width / 2, width / 2, 0, 0.2)
    bg = root.attachNewNode(cm.generate()); bg.setColor(0, 0, 0, 0.85)
    fgp = root.attachNewNode("fgp"); fgp.setPos(-width / 2, -0.01, 0.03)
    cm = CardMaker("fg"); cm.setFrame(0, width, 0, 0.14)
    fg = fgp.attachNewNode(cm.generate()); fg.setColor(*col, 1)
    root.setBillboardPointEye(); root.setLightOff(); root.setTwoSided(True)
    return root, fgp


STYLES = {  # (sx, sy, sz, x, y, z, colour-key, roll)  all in fractions of hero height
    "helm": [(.26, .26, .14, 0, 0, .95, "d", 0), (.06, .06, .2, -.28, 0, .82, "a", 0), (.06, .06, .2, .28, 0, .82, "a", 0)],
    "horns": [(.05, .05, .24, -.07, 0, 1.0, "a", 25), (.05, .05, .24, .07, 0, 1.0, "a", -25)],
    "hat": [(.34, .34, .03, 0, 0, .96, "d", 0), (.17, .17, .12, 0, 0, 1.02, "d", 0)],
    "ears": [(.05, .04, .16, -.07, 0, 1.0, "d", 0), (.05, .04, .16, .07, 0, 1.0, "d", 0), (.06, .3, .06, 0, -.22, .45, "a", 0)],
    "fists": [(.2, .2, .22, -.3, .05, .45, "a", 0), (.2, .2, .22, .3, .05, .45, "a", 0)],
    "wings": [(.5, .04, .26, -.3, -.15, .72, "a", 18), (.5, .04, .26, .3, -.15, .72, "a", -18)],
    "cape": [(.42, .05, .55, 0, -.15, .6, "a", 0)],
    "visor": [(.22, .1, .05, 0, .08, .89, "a", 0), (.05, .05, .3, 0, 0, 1.05, "a", 0)],
    "crown": [(.04, .04, .1, -.08, 0, 1.0, "a", 0), (.04, .04, .1, 0, 0, 1.03, "a", 0), (.04, .04, .1, .08, 0, 1.0, "a", 0)],
    "tail": [(.07, .35, .07, 0, -.22, .42, "a", 0), (.3, .3, .2, 0, 0, .96, "d", 0)],
}


def build_hero(name):
    d = HEROES[name]; h, w, c, a = d["h"], d["w"], d["color"], d["accent"]
    dark = tuple(x * 0.35 for x in c); col = {"c": c, "a": a, "d": dark}
    root = NodePath(name)

    def part(n, x, y, z, r=0):
        n.reparentTo(root); n.setPos(x, y, z); n.setR(r)

    part(make_box(w * .34, w * .34, h * .46, dark), -w * .22, 0, h * .23)
    part(make_box(w * .34, w * .34, h * .46, dark), w * .22, 0, h * .23)
    part(make_box(w, w * .55, h * .36, c), 0, 0, h * .63)
    part(make_box(w * .5, w * .1, h * .2, a), 0, w * .28, h * .66)
    part(make_sphere(h * .1, (.85, .72, .6)), 0, 0, h * .88)
    part(make_box(w * .25, w * .25, h * .34, c), -w * .65, 0, h * .62)
    part(make_box(w * .25, w * .25, h * .34, c), w * .65, 0, h * .62)
    part(make_box(w * .12, w * .9, w * .14, (.15, .15, .18)), w * .62, w * .5, h * .62)
    for sx, sy, sz, x, y, z, k, r in STYLES[d["style"]]:
        part(make_box(sx * h, sy * h, sz * h, col[k]), x * h, y * h, z * h, r)
    return root


def build_creep(team):
    t = TEAMCOL[team]; dk = tuple(x * .45 for x in t); root = NodePath("creep")
    b = make_box(1.0, .8, 1.4, dk); b.reparentTo(root); b.setZ(.9)
    s = make_sphere(.4, t); s.reparentTo(root); s.setZ(1.9); s.setLightOff()
    return root


def build_struct(kind, team):
    t = TEAMCOL[team]; dk = tuple(x * .4 for x in t); root = NodePath(kind)
    if kind == "tower":
        for n, z in ((make_box(5, 5, 3, (.12, .12, .15)), 1.5), (make_box(3, 3, 13, dk), 9.5)):
            n.reparentTo(root); n.setZ(z)
        o = make_sphere(2.0, t); o.reparentTo(root); o.setZ(17); o.setLightOff()
    else:
        for n, z in ((make_box(18, 18, 6, (.12, .12, .15)), 3), (make_box(8, 8, 22, dk), 17)):
            n.reparentTo(root); n.setZ(z)
        o = make_sphere(5, t); o.reparentTo(root); o.setZ(32); o.setLightOff()
    return root


# ---------------------------------------------------------------- networking
def norm_url(url):
    url = url.strip()
    if url.startswith("http://"): url = "ws://" + url[7:]
    elif url.startswith("https://"): url = "wss://" + url[8:]
    elif not url.startswith(("ws://", "wss://")):
        url = ("ws://" if url.startswith(("localhost", "127.")) else "wss://") + url
    if url.count("/") < 3: url = url.rstrip("/") + "/ws"
    return url


class Net:
    def __init__(self, url):
        self.url = url; self.q = queue.Queue(); self.ws = None; self.ok = False; self.err = None
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        try:
            self.ws = connect(self.url, max_size=None, open_timeout=60)
            self.ok = True
            for m in self.ws: self.q.put(json.loads(m))
        except Exception as e:
            self.err = str(e) or "connection closed"
        self.ok = False

    def send(self, **d):
        if self.ws and self.ok:
            try: self.ws.send(json.dumps(d))
            except Exception: pass


# ---------------------------------------------------------------- game
class Deadslop(ShowBase):
    def __init__(self, url):
        ShowBase.__init__(self)
        self.disableMouse()
        self.mode = "menu"; self.net = None; self.snap = None; self.ld = None; self.me = None
        self.nodes = {}; self.fxs = []; self.pnodes = []; self.casts = []
        self.keys = dict(w=0, a=0, s=0, d=0); self.fire = 0; self.sendt = 0.0
        self.yaw = 0.0; self.pitch = -8.0; self.locked = False; self.shop_open = False
        self.pick_hero = "Abrams"; self.banner_t = 0.0
        self.setBackgroundColor(.04, .06, .09)
        self.setup_lights(); self.world = self.render.attachNewNode("world"); self.build_world()
        self.preview = self.render.attachNewNode("preview"); self.set_preview()
        self.ui_menu = self.aspect2d.attachNewNode("menu"); self.ui_lobby = self.aspect2d.attachNewNode("lobby")
        self.hud = self.aspect2d.attachNewNode("hud")
        self.build_menu(url); self.build_lobby(); self.build_hud()
        self.show_mode("menu")
        for k in self.keys:
            self.accept(k, self.setkey, [k, 1]); self.accept(k + "-up", self.setkey, [k, 0])
        for i in range(4): self.accept(str(i + 1), self.casts.append, [i])
        self.accept("mouse1", self.setfire, [1]); self.accept("mouse1-up", self.setfire, [0])
        self.accept("b", self.toggle_shop); self.accept("escape", self.toggle_lock)
        self.taskMgr.add(self.update, "update")

    # ---- scene
    def setup_lights(self):
        al = AmbientLight("a"); al.setColor((.38, .42, .52, 1)); self.render.setLight(self.render.attachNewNode(al))
        dl = DirectionalLight("d"); dl.setColor((1.0, .85, .62, 1))
        n = self.render.attachNewNode(dl); n.setHpr(-35, -55, 0); self.render.setLight(n)
        fog = Fog("f"); fog.setColor(.04, .06, .09); fog.setExpDensity(.006); self.render.setFog(fog)

    def build_world(self):
        w = self.world; rng = random.Random(7)
        g = make_box(170, 2 * BASE_Y + 80, 1, (.09, .11, .13)); g.reparentTo(w); g.setZ(-.5)
        for lx in LANES_X:
            s = make_box(10, 2 * BASE_Y + 30, .12, (.32, .25, .14)); s.reparentTo(w); s.setPos(lx, 0, .06)
            for y in range(-120, 125, 24):
                for sx in (-6.5, 6.5):
                    p = make_box(.3, .3, 6, (.1, .1, .12)); p.reparentTo(w); p.setPos(lx + sx, y, 3)
                    l = make_sphere(.45, (1, .85, .5)); l.reparentTo(w); l.setPos(lx + sx, y, 6.2); l.setLightOff()
        for _ in range(150):
            x, y = rng.uniform(-80, 80), rng.uniform(-160, 160)
            if min(abs(x - lx) for lx in LANES_X) < 11 or abs(y) > 118 and abs(x) < 14: continue
            bh = rng.uniform(8, 34); tint = rng.uniform(.8, 1.3)
            b = make_box(rng.uniform(7, 14), rng.uniform(7, 14), bh, (.16 * tint, .15 * tint, .2 * tint))
            b.reparentTo(w); b.setPos(x, y, bh / 2)
            if rng.random() < .5:
                t = make_box(2, 2, 1, (1, .8, .4)); t.reparentTo(b); t.setPos(0, 0, bh / 2 + .5); t.setLightOff()
        for sx in (-84, 84):
            wl = make_box(2, 2 * BASE_Y + 80, 14, (.1, .1, .13)); wl.reparentTo(w); wl.setPos(sx, 0, 7)

    def set_preview(self):
        for c in self.preview.getChildren(): c.removeNode()
        m = build_hero(self.pick_hero); m.reparentTo(self.preview); m.setScale(1.1)
        self.preview.setPos(2.4, 0, 0)

    # ---- ui
    def txt(self, parent, text, pos, scale=.06, fg=(1, .92, .75, 1), align=TextNode.ALeft):
        return OnscreenText(text=text, pos=pos, scale=scale, fg=fg, align=align, parent=parent,
                            mayChange=True, shadow=(0, 0, 0, 1))

    def btn(self, parent, text, pos, cmd, args=(), scale=.05, w=None):
        kw = dict(frameSize=w) if w else {}
        return DirectButton(parent=parent, text=text, pos=pos, scale=scale, command=cmd, extraArgs=list(args),
                            frameColor=(.16, .12, .07, .92), text_fg=(1, .85, .5, 1), relief=DGG.FLAT,
                            pad=(.6, .3), **kw)

    def build_menu(self, url):
        m = self.ui_menu
        self.txt(m, "D E A D S L O P", (0, .55), .15, (1, .7, .25, 1), TextNode.ACenter)
        self.txt(m, "Name", (-.6, .22), .05)
        self.e_name = DirectEntry(parent=m, initialText=f"Player{random.randint(10, 99)}", scale=.05,
                                  pos=(-.6, 0, .13), width=24, numLines=1, focus=0, frameColor=(0, 0, 0, .6),
                                  text_fg=(1, 1, 1, 1))
        self.txt(m, "Server URL", (-.6, 0), .05)
        self.e_url = DirectEntry(parent=m, initialText=url, scale=.05, pos=(-.6, 0, -.09), width=24, numLines=1,
                                 focus=0, frameColor=(0, 0, 0, .6), text_fg=(1, 1, 1, 1))
        self.btn(m, "CONNECT", (0, 0, -.3), self.connect, scale=.07)
        self.t_status = self.txt(m, "", (0, -.45), .045, (1, .6, .5, 1), TextNode.ACenter)

    def build_lobby(self):
        r = self.ui_lobby
        self.txt(r, "LOBBY", (-1.7, .88), .09, (1, .7, .25, 1))
        self.t_team = [self.txt(r, "", (-1.7, .7), .05, tuple(list(TEAMCOL[0]) + [1])),
                       self.txt(r, "", (-.7, .7), .05, tuple(list(TEAMCOL[1]) + [1]))]
        self.btn(r, "Join Amber Hand", (-1.35, 0, .12), self.join_team, [0], .045)
        self.btn(r, "Join Sapphire Flame", (-.5, 0, .12), self.join_team, [1], .045)
        for i, n in enumerate(HEROES):
            self.btn(r, n, (-1.45 + (i % 4) * .5, 0, -.1 - (i // 4) * .13), self.choose, [n], .04)
        self.t_info = self.txt(r, "", (.35, .55), .045)
        self.b_ready = self.btn(r, "READY / START", (-.5, 0, -.72), self.ready, scale=.07)
        self.txt(r, "Pick a hero, pick a team, press READY. Bots fill empty slots (4v4).", (-1.7, -.9), .04)

    def build_hud(self):
        h = self.hud
        self.hpbar = DirectWaitBar(parent=h, range=1000, value=1000, pos=(0, 0, -.9), frameSize=(-.55, .55, -.03, .03),
                                   barColor=(.2, .85, .3, 1), frameColor=(0, 0, 0, .7))
        self.t_hp = self.txt(h, "", (0, -.915), .04, align=TextNode.ACenter)
        self.t_souls = self.txt(h, "", (-1.7, -.9), .06, (.5, 1, .9, 1))
        self.t_items = self.txt(h, "", (-1.7, -.8), .035)
        self.t_ab = [self.txt(h, "", (-.45 + i * .3, -.7), .04, align=TextNode.ACenter) for i in range(4)]
        self.txt(h, "+", (0, -.02), .08, (1, 1, 1, .8), TextNode.ACenter)
        self.t_top = self.txt(h, "", (0, .92), .05, align=TextNode.ACenter)
        self.t_score = self.txt(h, "", (-1.75, .92), .033)
        self.t_banner = self.txt(h, "", (0, .3), .11, (1, .8, .3, 1), TextNode.ACenter)
        self.t_hint = self.txt(h, "WASD move | mouse aim | LMB shoot | 1-4 abilities | B shop | Esc mouse", (0, -.99), .03,
                               (.7, .7, .7, 1), TextNode.ACenter)
        self.mm = DirectFrame(parent=h, frameColor=(0, 0, 0, .55), frameSize=(-.2, .2, -.4, .4), pos=(1.45, 0, -.5))
        cm = CardMaker("d"); cm.setFrame(-.5, .5, -.5, .5); self.dots = []
        for _ in range(100):
            d = self.mm.attachNewNode(cm.generate()); d.hide(); self.dots.append(d)
        self.shop = DirectFrame(parent=h, frameColor=(0, 0, 0, .85), frameSize=(-1.2, 1.2, -.75, .75))
        cats = ["Weapon", "Vitality", "Spirit"]
        for ci, c in enumerate(cats):
            self.txt(self.shop, c.upper(), (-1.05 + ci * .75, .62), .05, (1, .7, .25, 1))
            for ri, (n, it) in enumerate([x for x in ITEMS.items() if x[1]["cat"] == c]):
                self.btn(self.shop, f"{n}\n{it['cost']} souls", (-.78 + ci * .75, 0, .48 - ri * .2), self.buy, [n],
                         .038, (-8.5, 8.5, -1.5, 1.9))
        self.txt(self.shop, "Press B to close", (0, -.68), .04, align=TextNode.ACenter)
        self.shop.hide()

    def show_mode(self, m):
        self.mode = m
        for n, u in (("menu", self.ui_menu), ("lobby", self.ui_lobby), ("game", self.hud)):
            u.show() if n == m else u.hide()
        if m == "game":
            self.world.show(); self.preview.hide(); self.set_lock(True)
        else:
            self.world.hide(); self.preview.show(); self.set_lock(False); self.shop_open = False; self.shop.hide()
            self.camera.setPos(0, -8, 2.2); self.camera.lookAt(0, 0, 1.4)
            for n in self.nodes.values(): n["np"].removeNode()
            self.nodes = {}; self.me = None; self.snap = None

    # ---- input / actions
    def setkey(self, k, v): self.keys[k] = v
    def setfire(self, v): self.fire = v if (self.mode == "game" and self.locked) else 0

    def set_lock(self, v):
        self.locked = v
        p = WindowProperties(); p.setCursorHidden(v); self.win.requestProperties(p)
        if v: self.win.movePointer(0, self.win.getXSize() // 2, self.win.getYSize() // 2)

    def toggle_lock(self):
        if self.mode == "game" and not self.shop_open: self.set_lock(not self.locked)

    def toggle_shop(self):
        if self.mode != "game": return
        self.shop_open = not self.shop_open
        self.shop.show() if self.shop_open else self.shop.hide()
        self.set_lock(not self.shop_open)

    def connect(self):
        if self.net: return
        url = norm_url(self.e_url.get()); self.t_status.setText(f"Connecting to {url} ... (free hosts can take ~1 min to wake)")
        self.net = Net(url)

    def join_team(self, t): self.net and self.net.send(t="team", team=t)

    def choose(self, n):
        self.pick_hero = n; self.set_preview()
        d = HEROES[n]
        lines = [f"{n}   HP {d['hp']}  Speed {d['speed']}  Gun {d['gun']}"] + \
                [f"{i + 1}. {a['name']}  ({a['kind']}, {a['cd']}s)" for i, a in enumerate(d["abilities"])]
        self.t_info.setText("\n".join(lines))
        self.net and self.net.send(t="hero", hero=n)

    def ready(self):
        self.net and self.net.send(t="ready")

    def buy(self, name): self.net and self.net.send(t="buy", item=name)

    # ---- messages
    def pump(self):
        if not self.net: return
        if self.net.err and self.mode == "menu":
            self.t_status.setText("Failed: " + self.net.err); self.net = None; return
        if self.net.ok and self.mode == "menu":
            self.net.send(t="join", name=self.e_name.get()); self.choose(self.pick_hero); self.show_mode("lobby")
        last = None
        while not self.net.q.empty():
            m = self.net.q.get()
            if m["t"] == "snap": last = m
            elif m["t"] == "lobby":
                self.ld = m
                if self.mode == "game" and m["state"] == "lobby": self.show_mode("lobby")
                if self.mode == "lobby": self.refresh_lobby()
        if last:
            if self.mode == "lobby": self.show_mode("game")
            if self.mode == "game": self.snap = last
        if self.net.err and self.mode != "menu":
            err = self.net.err; self.net = None; self.show_mode("menu"); self.t_status.setText("Disconnected: " + err)

    def refresh_lobby(self):
        d = self.ld; lines = [[], []]
        for p in d["players"]:
            lines[p["team"]].append(f"{p['name']} - {p['hero']}{'  [READY]' if p['ready'] else ''}")
        for i in (0, 1): self.t_team[i].setText(TEAMS[i].upper() + "\n" + "\n".join(lines[i]))
        self.b_ready["text"] = "JOIN MATCH" if d["state"] == "game" else "READY / START"

    # ---- entities
    def get_node(self, id, kind, team, hero=None, name=""):
        n = self.nodes.get(id)
        if n: n["seen"] = True; return n
        root = self.world.attachNewNode("e")
        if kind == "hero": model = build_hero(hero); bw, bz = 2.6, HEROES[hero]["h"] + .7
        elif kind == "creep": model = build_creep(team); bw, bz = 1.6, 2.6
        else: model = build_struct(kind, team); bw, bz = (6, 21) if kind == "tower" else (12, 36)
        model.reparentTo(root)
        if kind == "hero":
            ring = make_sphere(1.6, TEAMCOL[team]); ring.setSz(.03); ring.setLightOff(); ring.reparentTo(root); ring.setZ(.1)
        bar, fg = make_bar(bw, TEAMCOL[team]); bar.reparentTo(root); bar.setZ(bz)
        if kind == "hero":
            tn = TextNode("n"); tn.setText(name); tn.setAlign(TextNode.ACenter); tn.setTextColor(1, 1, 1, 1)
            t = bar.attachNewNode(tn); t.setScale(.45); t.setPos(0, 0, .28)
        n = dict(np=root, model=model, fg=fg, tx=0, ty=0, th=0, seen=True, kind=kind, init=False)
        self.nodes[id] = n
        return n

    def apply_snap(self, s):
        for n in self.nodes.values(): n["seen"] = False
        you = s["you"]; self.me = you["id"]
        def put(n, x, y, h, hp, mhp, dead=False):
            n["tx"], n["ty"], n["th"] = x, y, h
            n["fg"].setSx(max(0.001, hp / max(1, mhp)))
            if not n["init"]: n["np"].setPos(x, y, 0); n["init"] = True
            n["np"].hide() if dead else n["np"].show()
        for r in s["H"]:
            n = self.get_node(r[0], "hero", r[1], r[2], r[3]); put(n, r[4], r[5], r[6], r[7], r[8], r[9])
        for r in s["C"]:
            n = self.get_node(r[0], "creep", r[1]); put(n, r[2], r[3], r[6], r[4], r[5])
        for r in s["S"]:
            n = self.get_node(r[0], r[2], r[1]); put(n, r[3], r[4], 0 if r[1] == 0 else 180, r[5], r[6])
        for k in [k for k, n in self.nodes.items() if not n["seen"]]:
            self.nodes.pop(k)["np"].removeNode()
        for f in s["fx"]: self.add_fx(f)
        while len(self.pnodes) < len(s["P"]):
            p = make_sphere(.5, (1, 1, 1)); p.reparentTo(self.world); p.setLightOff(); self.pnodes.append(p)
        for i, p in enumerate(self.pnodes):
            if i < len(s["P"]):
                x, y, t = s["P"][i]; p.setPos(x, y, 1.8); p.setColor(*TEAMCOL[t], 1); p.show()
            else: p.hide()
        self.apply_hud(s)

    def add_fx(self, f):
        k = f[0]; now = globalClock.getFrameTime()
        if k in ("shot", "tshot", "beam"):
            ls = LineSegs(); ls.setThickness({"shot": 2, "tshot": 3, "beam": 6}[k]); ls.setColor(*TEAMCOL[f[5]], 1)
            ls.moveTo(f[1], f[2], 8 if k == "tshot" else 1.8); ls.drawTo(f[3], f[4], 1.8)
            np = self.world.attachNewNode(ls.create()); np.setLightOff()
            self.fxs.append([np, now, .25 if k == "beam" else .07, k, 0])
        elif k == "boom":
            np = make_sphere(1, TEAMCOL[f[4]]); np.reparentTo(self.world); np.setPos(f[1], f[2], 1.2)
            np.setLightOff(); np.setTransparency(TransparencyAttrib.MAlpha)
            self.fxs.append([np, now, .4, k, f[3]])

    def tick_fx(self):
        now = globalClock.getFrameTime()
        for f in self.fxs[:]:
            np, t0, dur, k, rad = f; fr = (now - t0) / dur
            if fr >= 1: np.removeNode(); self.fxs.remove(f); continue
            if k == "boom": np.setScale(max(.1, rad * (.4 + .6 * fr))); np.setAlphaScale(.55 * (1 - fr))

    def apply_hud(self, s):
        y = s["you"]; hero = HEROES[y["hero"]]
        self.hpbar["range"] = max(1, y["maxhp"]); self.hpbar["value"] = y["hp"]
        self.t_hp.setText(f"{y['hp']} / {y['maxhp']}" + (f"   (+{y['shield']} shield)" if y["shield"] else ""))
        self.t_souls.setText(f"SOULS {y['souls']}")
        self.t_items.setText("Items: " + (", ".join(y["items"]) or "none (press B)"))
        for i, a in enumerate(hero["abilities"]):
            cd = y["acd"][i]
            self.t_ab[i].setText(f"[{i + 1}] {a['name']}\n" + (f"{cd:.1f}s" if cd > 0 else "READY"))
            self.t_ab[i].setFg((.5, .5, .5, 1) if cd > 0 else (1, .9, .5, 1))
        bases = {r[1]: r[5] for r in s["S"] if r[2] == "base"}
        self.t_top.setText(f"{TEAMS[0]} patron {bases.get(0, 0)}   {s['time'] // 60}:{s['time'] % 60:02d}   "
                           f"{TEAMS[1]} patron {bases.get(1, 0)}")
        self.t_score.setText("\n".join(f"{'A' if r[1] == 0 else 'S'} {r[3]} ({r[2]}) {r[12]}/{r[13]}  {r[11]}"
                                       for r in sorted(s["H"], key=lambda r: r[1])))
        if s["win"] is not None: self.t_banner.setText(f"{TEAMS[s['win']].upper()} WINS")
        elif y["resp"] > 0 and y["hp"] <= 0: self.t_banner.setText(f"RESPAWN IN {int(y['resp']) + 1}")
        else: self.t_banner.setText("")
        pts = [(r[4], r[5], r[1], .03, r[0] == y["id"]) for r in s["H"] if not r[9]] + \
              [(r[2], r[3], r[1], .014, False) for r in s["C"]] + [(r[3], r[4], r[1], .04, False) for r in s["S"]]
        for i, d in enumerate(self.dots):
            if i < len(pts):
                x, yy, t, sz, own = pts[i]
                d.setPos(x / 80 * .19, -.01, yy / 150 * .39); d.setScale(sz)
                d.setColor(1, 1, 1, 1) if own else d.setColor(*TEAMCOL[t], 1); d.show()
            else: d.hide()

    # ---- main loop
    def update(self, task):
        dt = globalClock.getDt(); self.pump()
        if self.mode in ("menu", "lobby"):
            self.preview.setH(self.preview.getH() + 40 * dt)
            return task.cont
        if self.snap:
            s, self.snap = self.snap, None; self.apply_snap(s)
        if self.locked and self.mouseWatcherNode.hasMouse():
            p = self.win.getPointer(0); cx, cy = self.win.getXSize() // 2, self.win.getYSize() // 2
            self.yaw = (self.yaw - (p.getX() - cx) * .12) % 360
            self.pitch = max(-35, min(25, self.pitch - (p.getY() - cy) * .1))
            self.win.movePointer(0, cx, cy)
        for id, n in self.nodes.items():
            np = n["np"]; k = min(1, dt * 14)
            np.setPos(np.getX() + (n["tx"] - np.getX()) * k, np.getY() + (n["ty"] - np.getY()) * k, 0)
            th = self.yaw if id == self.me else n["th"]
            cur = n["model"].getH(); n["model"].setH(cur + ((th - cur + 180) % 360 - 180) * min(1, dt * 18))
        self.tick_fx()
        if self.me in self.nodes:
            c = self.nodes[self.me]["np"]
            self.camera.setPos(c.getX(), c.getY(), 1.7); self.camera.setHpr(self.yaw, self.pitch, 0)
            self.camera.setPos(self.camera, 1.4, -9.5, 2.2)
        self.sendt += dt
        if self.sendt > 1 / 30 and self.net:
            self.sendt = 0
            self.net.send(t="in", mx=self.keys["d"] - self.keys["a"], my=self.keys["w"] - self.keys["s"],
                          h=self.yaw, fire=bool(self.fire and self.locked), casts=self.casts[:4] if self.locked else [])
            self.casts = []
        return task.cont


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DEADSLOP_URL", DEFAULT_URL)
    Deadslop(url).run()
