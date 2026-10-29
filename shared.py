"""DEADSLOP shared data (used by both server and client)."""
TICK = 20
BASE_Y = 130
LANES_X = [-45, 0, 45]
GUN_RANGE = 55
TEAMS = ["Amber Hand", "Sapphire Flame"]
TEAMCOL = [(1.0, 0.62, 0.12), (0.2, 0.5, 1.0)]

# defaults for every ability field
ABDEF = dict(dmg=0, range=40, dist=0, radius=3, stun=0, slow=0, sdur=0,
             heal=0, shield=0, dur=0, boost=0, spd=32)


def A(name, kind, cd, **kw):
    return dict(name=name, kind=kind, cd=cd, **kw)


# kinds: proj (projectile), aoe (burst at self/in front), dash, buff, beam (hitscan)
# Slot 4 is the ultimate. Kits are loose approximations, numbers are my own.
HEROES = {
    "Abrams": dict(color=(0.65, 0.25, 0.2), accent=(1.0, 0.7, 0.2), hp=950, speed=7.0, gun=13,
                   h=2.4, w=1.5, style="helm", abilities=[
        A("Siphon Life", "beam", 7, dmg=55, range=13, heal=55),
        A("Shoulder Charge", "dash", 13, dist=18, dmg=60, radius=3.5, stun=1.2),
        A("Seismic Impact", "aoe", 18, dist=10, dmg=100, radius=8, stun=1.4),
        A("Infernal Resilience", "buff", 70, shield=350, dur=8, boost=0.15)]),
    "Infernus": dict(color=(0.35, 0.12, 0.1), accent=(1.0, 0.4, 0.05), hp=800, speed=7.2, gun=11,
                     h=2.1, w=1.2, style="horns", abilities=[
        A("Flame Dash", "dash", 10, dist=14, dmg=45, radius=3),
        A("Concussive Combustion", "proj", 16, dmg=55, radius=4, spd=22, range=60, stun=0.9),
        A("Catalyst", "aoe", 14, dmg=40, radius=8, slow=0.4, sdur=3),
        A("Afterburn", "aoe", 75, dmg=170, radius=12)]),
    "Haze": dict(color=(0.2, 0.22, 0.3), accent=(0.7, 0.9, 1.0), hp=720, speed=7.8, gun=10,
                 h=2.0, w=1.1, style="hat", abilities=[
        A("Sleep Dagger", "proj", 14, dmg=40, radius=2, spd=38, range=45, stun=1.6),
        A("Smoke Bomb", "aoe", 16, dist=6, dmg=30, radius=6, slow=0.5, sdur=3),
        A("Fixation", "buff", 20, boost=0.35, dur=6, shield=80),
        A("Bullet Dance", "beam", 80, dmg=230, range=35)]),
    "Silver": dict(color=(0.55, 0.55, 0.6), accent=(0.9, 0.9, 1.0), hp=900, speed=7.4, gun=12,
                   h=2.3, w=1.4, style="ears", abilities=[
        A("Lycan Leap", "dash", 11, dist=16, dmg=50, radius=3, slow=0.3, sdur=2),
        A("Boot Kick", "aoe", 12, dist=4, dmg=55, radius=4, stun=0.7),
        A("Entangling Bola", "proj", 15, dmg=35, radius=4, spd=30, slow=0.6, sdur=3),
        A("Go for the Throat", "beam", 70, dmg=150, range=9, heal=150)]),
    "Billy": dict(color=(0.7, 0.55, 0.3), accent=(0.9, 0.2, 0.2), hp=880, speed=7.3, gun=11,
                  h=2.2, w=1.5, style="fists", abilities=[
        A("Bashdown", "dash", 12, dist=12, dmg=55, radius=4, stun=0.6),
        A("Blasted", "proj", 9, dmg=65, radius=2.5, spd=45, range=50),
        A("Chain Gang", "aoe", 17, dmg=30, radius=8, slow=0.5, sdur=3),
        A("Rocket Punch", "proj", 80, dmg=220, radius=4, spd=40, range=60, stun=1.5)]),
    "Vindicta": dict(color=(0.25, 0.2, 0.3), accent=(0.75, 0.3, 1.0), hp=700, speed=7.2, gun=15,
                     h=2.1, w=1.0, style="wings", abilities=[
        A("Stake", "proj", 14, dmg=55, radius=2, spd=40, range=55, stun=1.2),
        A("Flight", "buff", 22, boost=0.5, dur=5),
        A("Crow Familiar", "proj", 11, dmg=40, radius=3, spd=28, range=45, slow=0.4, sdur=2),
        A("Assassinate", "beam", 85, dmg=280, range=70)]),
    "Drifter": dict(color=(0.15, 0.12, 0.18), accent=(0.8, 0.1, 0.3), hp=820, speed=7.6, gun=12,
                    h=2.2, w=1.2, style="cape", abilities=[
        A("Rend", "aoe", 7, dist=4, dmg=50, radius=4),
        A("Stalker", "dash", 12, dist=12, dmg=40, radius=3, slow=0.3, sdur=2),
        A("Bloodscent", "buff", 20, boost=0.3, dur=5, heal=90),
        A("Eternal Night", "aoe", 80, dmg=130, radius=14, slow=0.4, sdur=4)]),
    "Seven": dict(color=(0.2, 0.3, 0.45), accent=(0.4, 0.9, 1.0), hp=850, speed=7.0, gun=11,
                  h=2.3, w=1.3, style="visor", abilities=[
        A("Lightning Ball", "proj", 10, dmg=55, radius=3, spd=20, range=50),
        A("Static Charge", "aoe", 14, dist=8, dmg=45, radius=5, stun=1.0),
        A("Power Surge", "buff", 18, boost=0.2, shield=120, dur=6),
        A("Storm Cloud", "aoe", 80, dmg=200, radius=13)]),
    "Lady Geist": dict(color=(0.3, 0.45, 0.3), accent=(0.5, 1.0, 0.6), hp=760, speed=7.1, gun=11,
                       h=2.1, w=1.1, style="crown", abilities=[
        A("Essence Bomb", "proj", 9, dmg=65, radius=3.5, spd=28, range=45),
        A("Life Drain", "beam", 14, dmg=70, range=16, heal=70),
        A("Malice", "buff", 22, boost=0.15, shield=150, dur=8),
        A("Soul Exchange", "beam", 85, dmg=160, range=30, heal=200)]),
    "Bebop": dict(color=(0.6, 0.3, 0.5), accent=(1.0, 0.85, 0.2), hp=1000, speed=6.8, gun=10,
                  h=2.5, w=1.8, style="tail", abilities=[
        A("Exploding Uppercut", "aoe", 10, dist=4, dmg=60, radius=4, stun=0.8),
        A("Sticky Bomb", "proj", 12, dmg=75, radius=4, spd=22, range=50),
        A("Hook", "proj", 16, dmg=30, radius=2, spd=45, range=40, stun=1.2),
        A("Hyperbeam", "beam", 80, dmg=260, range=25)]),
}

ITEMS = {
    "Basic Magazine": dict(cat="Weapon", cost=500, gun=0.12),
    "Close Quarters": dict(cat="Weapon", cost=500, gun=0.10, speed=0.03),
    "Monster Rounds": dict(cat="Weapon", cost=1250, gun=0.22),
    "Fleetfoot Rounds": dict(cat="Weapon", cost=1250, gun=0.14, speed=0.06),
    "Extra Health": dict(cat="Vitality", cost=500, hp=150),
    "Extra Regen": dict(cat="Vitality", cost=500, hp=50, regen=3),
    "Sprint Boots": dict(cat="Vitality", cost=500, speed=0.08),
    "Fortitude": dict(cat="Vitality", cost=1250, hp=350, regen=2),
    "Mystic Burst": dict(cat="Spirit", cost=500, spirit=0.12),
    "Extra Spirit": dict(cat="Spirit", cost=500, spirit=0.10, hp=50),
    "Improved Cooldown": dict(cat="Spirit", cost=1250, cdr=0.15, spirit=0.08),
    "Spirit Lifesteal": dict(cat="Spirit", cost=1250, ls=0.12, spirit=0.10),
}
