"""DEADSLOP server: lobby + authoritative 3-lane match simulation over websockets.
Run locally:  python server.py      (listens on $PORT or 10000)
"""
import asyncio, itertools, json, math, os, random, time
from aiohttp import web, WSMsgType
from shared import *

DT = 1.0 / TICK
HERE = os.path.dirname(os.path.abspath(__file__))
nid = itertools.count(1)
r1 = lambda v: round(v, 1)


def vec(h):
    r = math.radians(h)
    return -math.sin(r), math.cos(r)


def hdg(dx, dy):
    return math.degrees(math.atan2(-dx, dy))


def clampf(v, lo, hi):
    return max(lo, min(hi, v))


class Ent:
    def __init__(s, kind, team, x, y, hp, r=1.0, **kw):
        s.id = next(nid); s.kind = kind; s.team = team; s.x = x; s.y = y
        s.hp = s.maxhp = hp; s.r = r; s.h = 0.0
        s.stun = s.slow = s.slowt = s.shield = s.sht = s.boost = s.boostt = 0.0
        s.cd = 0.0
        s.__dict__.update(kw)


class Player:
    def __init__(s, ws=None, name="Player", bot=False):
        s.id = next(nid); s.ws = ws; s.name = name; s.bot = bot
        s.team = 0; s.hero = "Abrams"; s.ready = False; s.ent = None


class Match:
    def __init__(s):
        s.players = {}
        s.reset()

    # ---------- lobby ----------
    def reset(s):
        s.state = "lobby"; s.ents = {}; s.projs = []; s.fx = []
        s.t = 0.0; s.nextwave = 3.0; s.winner = None; s.endt = 0.0; s.dirty = True
        for p in list(s.players.values()):
            if p.bot:
                del s.players[p.id]
            else:
                p.ent = None; p.ready = False

    def humans(s):
        return [p for p in s.players.values() if not p.bot]

    def auto_team(s):
        c = [0, 0]
        for p in s.humans(): c[p.team] += 1
        return 0 if c[0] <= c[1] else 1

    def lobby(s, you):
        return dict(t="lobby", you=you, state=s.state, players=[
            dict(id=p.id, name=p.name, team=p.team, hero=p.hero, ready=p.ready)
            for p in s.players.values() if not p.bot])

    # ---------- match setup ----------
    def add(s, e):
        s.ents[e.id] = e
        return e

    def start(s):
        s.state = "game"; s.t = 0.0; s.nextwave = 3.0; s.winner = None
        for team in (0, 1):
            sg = -1 if team == 0 else 1
            s.add(Ent("base", team, 0, sg * BASE_Y, 6000, r=9, rng=30, dmg=40, rate=1.0))
            for lx in LANES_X:
                for ty in (50, 95):
                    s.add(Ent("tower", team, lx, sg * ty, 2500, r=2.5, rng=24, dmg=45, rate=1.2))
            n = len([p for p in s.players.values() if p.team == team])
            for i in range(max(0, 4 - n)):
                b = Player(name=f"Bot{i + 1}", bot=True); b.team = team
                b.hero = random.choice(list(HEROES)); s.players[b.id] = b
        for p in s.players.values():
            s.spawn_player(p)
        s.dirty = True

    def spawn_player(s, p):
        d = HEROES[p.hero]
        e = Ent("hero", p.team, 0, 0, d["hp"], r=1.1, pid=p.id, hero=p.hero, name=p.name,
                souls=600.0, items=[], acd=[0.0] * 4, resp=0.0, kills=0, deaths=0, mv=(0, 0),
                fire=False, casts=[], dash=None, gcd=0.0, bot=p.bot,
                lane=random.choice(LANES_X), gunmul=0.0, spirit=0.0, cdr=0.0, ls=0.0,
                regen=2.0, spdmul=0.0,
                ab=[dict(ABDEF, **a) for a in d["abilities"]])
        s.recalc(e); e.hp = e.maxhp; s.place(e)
        p.ent = e; s.add(e)

    def place(s, e):
        e.x = random.choice(LANES_X) + random.uniform(-4, 4)
        e.y = (-1 if e.team == 0 else 1) * (BASE_Y - 14)
        e.h = 0 if e.team == 0 else 180

    def recalc(s, e):
        st = dict(hp=0, speed=0, gun=0, spirit=0, cdr=0, ls=0, regen=0)
        for it in e.items:
            for k, v in ITEMS[it].items():
                if k in st: st[k] += v
        ratio = e.hp / e.maxhp
        e.maxhp = HEROES[e.hero]["hp"] + st["hp"]; e.hp = e.maxhp * ratio
        e.spdmul = st["speed"]; e.gunmul = st["gun"]; e.spirit = st["spirit"]
        e.cdr = min(0.4, st["cdr"]); e.ls = st["ls"]; e.regen = 2.0 + st["regen"]

    def buy(s, e, name):
        if not e or e.hp <= 0 or name not in ITEMS or name in e.items or len(e.items) >= 8: return
        if e.souls < ITEMS[name]["cost"]: return
        e.souls -= ITEMS[name]["cost"]; e.items.append(name); s.recalc(e)

    # ---------- combat helpers ----------
    def heroes(s):
        return [e for e in s.ents.values() if e.kind == "hero"]

    def enemies(s, e):
        return [t for t in s.ents.values() if t.team != e.team and t.hp > 0]

    def nearest(s, e, rng):
        best, bd = None, 1e9
        for t in s.enemies(e):
            d = math.hypot(t.x - e.x, t.y - e.y)
            if d - t.r < rng and d < bd: best, bd = t, d
        return best

    def ray(s, src, dx, dy, rng):
        best, bd = None, rng
        for t in s.enemies(src):
            vx, vy = t.x - src.x, t.y - src.y
            d = vx * dx + vy * dy
            if d < 0 or d > bd + t.r: continue
            if abs(vx * dy - vy * dx) <= t.r + 0.3:
                dd = max(d - t.r * 0.5, 0.0)
                if dd < bd: bd, best = dd, t
        return best, bd

    def speed(s, e, base):
        m = 1.0
        if e.boostt > 0: m += e.boost
        if e.slowt > 0: m -= e.slow
        return base * max(0.25, m)

    def status(s, e):
        e.stun = max(0.0, e.stun - DT)
        if e.slowt > 0: e.slowt -= DT
        if e.boostt > 0: e.boostt -= DT
        if e.sht > 0:
            e.sht -= DT
            if e.sht <= 0: e.shield = 0.0
        e.cd -= DT

    def hurt(s, t, dmg, src=None):
        if t.hp <= 0 or dmg <= 0: return
        if t.shield > 0:
            a = min(t.shield, dmg); t.shield -= a; dmg -= a
        t.hp -= dmg
        if src is not None and src.kind == "hero" and src.ls > 0:
            src.hp = min(src.maxhp, src.hp + dmg * src.ls)
        if t.hp <= 0: s.die(t, src)

    def die(s, t, src):
        t.hp = 0
        reward = {"hero": 300, "creep": 40, "tower": 450, "base": 0}[t.kind]
        if t.kind == "hero":
            t.deaths += 1; t.resp = min(30.0, 6 + s.t / 20.0); t.dash = None; t.fire = False
            if src is not None and src.kind == "hero": src.kills += 1
        near = [h for h in s.heroes() if h.team == 1 - t.team and h.hp > 0
                and math.hypot(h.x - t.x, h.y - t.y) < 50]
        if src is not None and src.kind == "hero" and src not in near: near.append(src)
        for h in near: h.souls += reward * (1.0 if h is src else 0.6)
        if t.kind == "base": s.winner = 1 - t.team

    def hit(s, e, t, ab):
        s.hurt(t, ab["dmg"] * (1 + e.spirit), e)
        if t.kind in ("hero", "creep"):
            if ab["stun"]: t.stun = max(t.stun, ab["stun"])
            if ab["slow"]: t.slow = ab["slow"]; t.slowt = ab["sdur"]

    def strike(s, e, cx, cy, ab):
        for t in s.enemies(e):
            if math.hypot(t.x - cx, t.y - cy) <= ab["radius"] + t.r: s.hit(e, t, ab)
        s.fx.append(["boom", r1(cx), r1(cy), ab["radius"], e.team])

    def shoot(s, e):
        e.gcd = 0.16
        dx, dy = vec(e.h)
        t, d = s.ray(e, dx, dy, GUN_RANGE)
        if t: s.hurt(t, HEROES[e.hero]["gun"] * (1 + e.gunmul), e)
        s.fx.append(["shot", r1(e.x), r1(e.y), r1(e.x + dx * d), r1(e.y + dy * d), e.team])

    def cast(s, e, i):
        ab = e.ab[i]
        if e.acd[i] > 0: return
        e.acd[i] = ab["cd"] * (1 - e.cdr)
        dx, dy = vec(e.h); k = ab["kind"]
        if k == "proj":
            s.projs.append(dict(x=e.x + dx, y=e.y + dy, dx=dx, dy=dy, spd=ab["spd"],
                                rng=ab["range"], team=e.team, src=e, ab=ab))
        elif k == "aoe":
            s.strike(e, e.x + dx * ab["dist"], e.y + dy * ab["dist"], ab)
        elif k == "dash":
            e.dash = [dx, dy, ab["dist"], ab]
        elif k == "buff":
            if ab["shield"]: e.shield += ab["shield"]; e.sht = ab["dur"] or 6
            if ab["heal"]: e.hp = min(e.maxhp, e.hp + ab["heal"] * (1 + e.spirit))
            if ab["boost"]: e.boost = ab["boost"]; e.boostt = ab["dur"]
            s.fx.append(["boom", r1(e.x), r1(e.y), 3, e.team])
        elif k == "beam":
            t, d = s.ray(e, dx, dy, ab["range"])
            if t:
                s.hit(e, t, ab)
                if ab["heal"]: e.hp = min(e.maxhp, e.hp + ab["heal"] * (1 + e.spirit))
            s.fx.append(["beam", r1(e.x), r1(e.y), r1(e.x + dx * d), r1(e.y + dy * d), e.team])

    # ---------- per-entity thinking ----------
    def wave(s):
        for team in (0, 1):
            sg = -1 if team == 0 else 1
            for lx in LANES_X:
                for i in range(4):
                    s.add(Ent("creep", team, lx + random.uniform(-1.5, 1.5),
                              sg * (BASE_Y - 20) + sg * i * 2.2, 320, r=0.8, dir=-sg))

    def think_creep(s, e):
        s.status(e)
        if e.stun > 0: return
        sp = s.speed(e, 5.0)
        t = s.nearest(e, 16)
        if t:
            dx, dy = t.x - e.x, t.y - e.y; d = math.hypot(dx, dy) or 1.0
            e.h = hdg(dx, dy)
            if d - t.r > 5:
                e.x += dx / d * sp * DT; e.y += dy / d * sp * DT
            elif e.cd <= 0:
                e.cd = 1.0; s.hurt(t, 12, e)
        else:
            e.y += e.dir * sp * DT; e.h = hdg(0, e.dir)

    def think_tower(s, e):
        e.cd -= DT
        t = s.nearest(e, e.rng)
        if t and e.cd <= 0:
            e.cd = e.rate; s.hurt(t, e.dmg, e)
            s.fx.append(["tshot", r1(e.x), r1(e.y), r1(t.x), r1(t.y), e.team])

    def bot_ai(s, e):
        t = s.nearest(e, 40)
        e.fire = False; e.mv = (0, 0)
        if t:
            dx, dy = t.x - e.x, t.y - e.y; d = math.hypot(dx, dy)
            e.h = hdg(dx, dy); e.fire = True
            e.mv = (math.sin(s.t * 1.3 + e.id) * 0.8, 1 if d > 22 else (-0.5 if d < 10 else 0))
            if random.random() < 0.03: e.casts.append(random.randrange(4))
        else:
            gx = e.lane - e.x; gy = (BASE_Y if e.team == 0 else -BASE_Y) - e.y
            e.h = hdg(gx, gy); e.mv = (0, 1)
        if e.souls > 600 and random.random() < 0.02:
            opts = [n for n, i in ITEMS.items() if n not in e.items and i["cost"] <= e.souls]
            if opts: s.buy(e, random.choice(opts))

    def think_hero(s, e):
        if e.hp <= 0:
            e.resp -= DT
            if e.resp <= 0:
                e.hp = e.maxhp; e.shield = 0.0; s.place(e)
            return
        s.status(e)
        e.souls += 10 * DT
        e.hp = min(e.maxhp, e.hp + e.regen * DT)
        for i in range(4): e.acd[i] = max(0.0, e.acd[i] - DT)
        e.gcd -= DT
        if e.bot: s.bot_ai(e)
        if e.stun <= 0:
            if e.dash:
                dx, dy, left, ab = e.dash
                st = min(left, 38 * DT)
                e.x += dx * st; e.y += dy * st; e.dash[2] -= st
                if e.dash[2] <= 0:
                    s.strike(e, e.x, e.y, ab); e.dash = None
            else:
                mx, my = e.mv
                f = vec(e.h); r = (f[1], -f[0])
                vx = f[0] * my + r[0] * mx; vy = f[1] * my + r[1] * mx
                n = math.hypot(vx, vy)
                if n > 1: vx /= n; vy /= n
                sp = s.speed(e, HEROES[e.hero]["speed"] * (1 + e.spdmul))
                e.x += vx * sp * DT; e.y += vy * sp * DT
            if e.fire and e.gcd <= 0 and not e.dash: s.shoot(e)
            for i in e.casts:
                if 0 <= i < 4: s.cast(e, i)
        e.casts = []
        e.x = clampf(e.x, -72, 72); e.y = clampf(e.y, -BASE_Y - 14, BASE_Y + 14)

    def move_projs(s):
        for p in s.projs[:]:
            m = p["spd"] * DT
            p["x"] += p["dx"] * m; p["y"] += p["dy"] * m; p["rng"] -= m
            hit = None
            for t in s.ents.values():
                if t.team != p["team"] and t.hp > 0 and \
                        math.hypot(t.x - p["x"], t.y - p["y"]) < t.r + 1.0:
                    hit = t; break
            if hit or p["rng"] <= 0:
                if hit: s.strike(p["src"], p["x"], p["y"], p["ab"])
                s.projs.remove(p)

    def tick(s):
        if s.state != "game": return
        s.t += DT; s.fx = []
        if s.winner is not None:
            if not s.endt: s.endt = s.t + 10
            elif s.t >= s.endt:
                s.reset(); return
            return
        if s.t >= s.nextwave:
            s.nextwave += 28; s.wave()
        for e in list(s.ents.values()):
            if e.kind == "hero": s.think_hero(e)
            elif e.kind == "creep": s.think_creep(e)
            else: s.think_tower(e)
        s.move_projs()
        for k in [k for k, e in s.ents.items() if e.hp <= 0 and e.kind != "hero"]:
            if s.ents[k].kind != "base": del s.ents[k]

    # ---------- snapshots ----------
    def snap(s):
        H, C, S = [], [], []
        for e in s.ents.values():
            if e.kind == "hero":
                H.append([e.id, e.team, e.hero, e.name, r1(e.x), r1(e.y), round(e.h), int(e.hp),
                          int(e.maxhp), int(e.hp <= 0), int(e.stun > 0), int(e.souls), e.kills, e.deaths])
            elif e.kind == "creep":
                C.append([e.id, e.team, r1(e.x), r1(e.y), int(e.hp), int(e.maxhp), round(e.h)])
            else:
                S.append([e.id, e.team, e.kind, r1(e.x), r1(e.y), int(e.hp), int(e.maxhp)])
        return dict(t="snap", time=int(s.t), win=s.winner, H=H, C=C, S=S,
                    P=[[r1(p["x"]), r1(p["y"]), p["team"]] for p in s.projs], fx=s.fx)

    def you(s, p):
        e = p.ent
        return dict(id=e.id, hero=e.hero, hp=int(e.hp), maxhp=int(e.maxhp), souls=int(e.souls),
                    items=e.items, acd=[r1(x) for x in e.acd], resp=r1(e.resp), shield=int(e.shield))


G = Match()


# ---------- networking ----------
async def send(p, msg):
    try:
        await p.ws.send_str(msg)
    except Exception:
        pass


async def broadcast():
    if G.dirty:
        G.dirty = False
        await asyncio.gather(*[send(p, json.dumps(G.lobby(p.id))) for p in G.players.values() if p.ws])
    if G.state == "game":
        common = G.snap()
        await asyncio.gather(*[send(p, json.dumps(dict(common, you=G.you(p))))
                               for p in G.players.values() if p.ws and p.ent])


async def game_loop(app):
    async def run():
        while True:
            t0 = time.perf_counter()
            try:
                G.tick()
                await broadcast()
            except Exception as ex:
                print("tick error:", repr(ex))
            await asyncio.sleep(max(0.0, DT - (time.perf_counter() - t0)))
    app["loop"] = asyncio.create_task(run())


def handle(p, m):
    t = m.get("t")
    if t == "join":
        p.name = (str(m.get("name", "Player"))[:16] or "Player"); p.team = G.auto_team()
    elif t == "team" and not p.ent:
        p.team = 1 if m.get("team") == 1 else 0
    elif t == "hero" and not p.ent and m.get("hero") in HEROES:
        p.hero = m["hero"]
    elif t == "ready":
        p.ready = True
        if G.state == "game" and not p.ent:
            G.spawn_player(p)
        elif G.state == "lobby" and all(q.ready for q in G.humans()):
            G.start()
    elif t == "in" and p.ent:
        e = p.ent
        try:
            e.mv = (clampf(float(m.get("mx", 0)), -1, 1), clampf(float(m.get("my", 0)), -1, 1))
            e.h = float(m.get("h", e.h)) % 360; e.fire = bool(m.get("fire"))
            e.casts += [int(i) for i in m.get("casts", [])][:4]
        except (TypeError, ValueError):
            pass
        return
    elif t == "buy" and p.ent:
        G.buy(p.ent, m.get("item")); return
    G.dirty = True


async def ws_handler(req):
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=4096)
    await ws.prepare(req)
    p = Player(ws=ws); p.team = G.auto_team()
    G.players[p.id] = p; G.dirty = True
    try:
        async for m in ws:
            if m.type == WSMsgType.TEXT:
                try:
                    handle(p, json.loads(m.data))
                except json.JSONDecodeError:
                    pass
    finally:
        G.players.pop(p.id, None)
        if p.ent: G.ents.pop(p.ent.id, None)
        if G.state == "game" and not G.humans(): G.reset()
        G.dirty = True
    return ws


PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>DEADSLOP</title><style>body{background:#0b0f16;color:#e9d9b0;font:16px/1.6 Georgia,serif;max-width:720px;margin:48px auto;padding:0 20px}
h1{letter-spacing:.3em;color:#ffb347}code,pre{background:#161c28;padding:2px 6px;border-radius:4px;color:#8fe3ff}pre{padding:12px;overflow:auto}
a{color:#ffb347}.s{color:#7f8}</style>
<h1>DEADSLOP</h1><p>Fan-made 3D lane-brawler. Server status: <span class=s>online</span> &middot; players connected: %PLAYERS% &middot; state: %STATE%</p>
<p>Panda3D is a desktop engine, so you play with a small Python client that connects to this server.</p>
<ol><li>Install Python 3.9+ and run <code>pip install panda3d websockets</code></li>
<li>Download <a href="/dl/client.py">client.py</a> and <a href="/dl/shared.py">shared.py</a> into one folder</li>
<li>Run:</li></ol><pre>python client.py %WS%</pre>
<p>Controls: WASD move &middot; mouse aim &middot; LMB shoot &middot; 1-4 abilities (4 = ultimate) &middot; B shop &middot; Esc free the mouse.</p>"""


async def index(req):
    return web.FileResponse(os.path.join(HERE, "index.html"))


async def data(req):
    return web.json_response(dict(heroes=HEROES, items=ITEMS, teams=TEAMS, teamcol=TEAMCOL,
                                  lanes=LANES_X, base_y=BASE_Y))


async def desktop(req):
    scheme = "wss" if req.headers.get("X-Forwarded-Proto", req.scheme) == "https" else "ws"
    html = PAGE.replace("%WS%", f"{scheme}://{req.host}/ws").replace("%PLAYERS%", str(len(G.humans()))) \
        .replace("%STATE%", G.state)
    return web.Response(text=html, content_type="text/html")


async def download(req):
    name = req.match_info["name"]
    if name not in ("client.py", "shared.py"): raise web.HTTPNotFound()
    return web.FileResponse(os.path.join(HERE, name))


def make_app():
    app = web.Application()
    app.add_routes([web.get("/", index), web.get("/data", data), web.get("/desktop", desktop),
                    web.get("/ws", ws_handler), web.get("/dl/{name}", download),
                    web.get("/health", lambda r: web.Response(text="ok"))])
    app.on_startup.append(game_loop)
    return app


if __name__ == "__main__":
    web.run_app(make_app(), host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
