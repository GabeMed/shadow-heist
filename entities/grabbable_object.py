import math
from panda3d.core import (
    GeomVertexFormat, GeomVertexData, GeomVertexWriter,
    Geom, GeomTriangles, GeomNode, NodePath,
    TransparencyAttrib,
)
import config


# ── Helpers de geometria procedural ───────────────────────────────────────

def _face_normal(v0, v1, v2):
    """Normal plana de um triângulo (produto vetorial normalizado)."""
    e1x, e1y, e1z = v1[0]-v0[0], v1[1]-v0[1], v1[2]-v0[2]
    e2x, e2y, e2z = v2[0]-v0[0], v2[1]-v0[1], v2[2]-v0[2]
    nx = e1y*e2z - e1z*e2y
    ny = e1z*e2x - e1x*e2z
    nz = e1x*e2y - e1y*e2x
    mag = (nx*nx + ny*ny + nz*nz) ** 0.5
    if mag < 1e-10:
        return (0.0, 0.0, 1.0)
    return (nx/mag, ny/mag, nz/mag)


def _geom_from_triangles(tri_faces):
    """
    Cria um NodePath a partir de lista de triângulos (v0, v1, v2).
    Normal plana calculada automaticamente por face (flat shading).
    """
    fmt   = GeomVertexFormat.getV3n3()
    vdata = GeomVertexData("mesh", fmt, Geom.UHStatic)
    vdata.setNumRows(len(tri_faces) * 3)

    wpos  = GeomVertexWriter(vdata, "vertex")
    wnrm  = GeomVertexWriter(vdata, "normal")
    tris  = GeomTriangles(Geom.UHStatic)
    vi    = 0

    for v0, v1, v2 in tri_faces:
        n = _face_normal(v0, v1, v2)
        for v in (v0, v1, v2):
            wpos.addData3(*v)
            wnrm.addData3(*n)
        tris.addVertices(vi, vi+1, vi+2)
        vi += 3

    geom  = Geom(vdata)
    geom.addPrimitive(tris)
    gnode = GeomNode("geom")
    gnode.addGeom(geom)
    return NodePath(gnode)


def _quad(a, b, c, d):
    """Divide um quad (a,b,c,d — CCW de fora) em dois triângulos."""
    return [(a, b, c), (a, c, d)]


# ── Construtores de formas ────────────────────────────────────────────────

def _build_box(w, d, h):
    """Caixa sólida centrada na origem."""
    hw, hd, hh = w/2, d/2, h/2
    b = [(-hw,-hd,-hh), ( hw,-hd,-hh), ( hw, hd,-hh), (-hw, hd,-hh)]
    t = [(-hw,-hd, hh), ( hw,-hd, hh), ( hw, hd, hh), (-hw, hd, hh)]
    faces = (
        _quad(b[0], b[3], b[2], b[1]) +   # baixo  (−Z)
        _quad(t[0], t[1], t[2], t[3]) +   # topo   (+Z)
        _quad(b[0], b[1], t[1], t[0]) +   # frente (−Y)
        _quad(b[2], b[3], t[3], t[2]) +   # trás   (+Y)
        _quad(b[3], b[0], t[0], t[3]) +   # esq    (−X)
        _quad(b[1], b[2], t[2], t[1])     # dir    (+X)
    )
    return _geom_from_triangles(faces)


def _build_trapezoid_prism(hw_bot, hd_bot, height, taper=0.82):
    """
    Prisma trapezoidal centrado na origem — topo afunilado em relação à base.
    Forma clássica de barra de ouro: largura e profundidade maiores embaixo.
    taper: fração do topo em relação à base (0.82 ≈ 18 % menor).
    """
    hh     = height / 2
    hw_t   = hw_bot * taper
    hd_t   = hd_bot * taper

    b = [(-hw_bot,-hd_bot,-hh), ( hw_bot,-hd_bot,-hh),
         ( hw_bot, hd_bot,-hh), (-hw_bot, hd_bot,-hh)]
    t = [(-hw_t,  -hd_t,   hh), ( hw_t,  -hd_t,   hh),
         ( hw_t,   hd_t,   hh), (-hw_t,   hd_t,   hh)]

    faces = (
        _quad(b[0], b[3], b[2], b[1]) +   # base   (−Z)
        _quad(t[0], t[1], t[2], t[3]) +   # topo   (+Z)
        _quad(b[0], b[1], t[1], t[0]) +   # frente (−Y, inclinado)
        _quad(b[2], b[3], t[3], t[2]) +   # trás   (+Y, inclinado)
        _quad(b[3], b[0], t[0], t[3]) +   # esq    (−X, inclinado)
        _quad(b[1], b[2], t[2], t[1])     # dir    (+X, inclinado)
    )
    return _geom_from_triangles(faces)


def _build_octahedron(radius, ht, hb):
    """
    Octaedro regular (duas pirâmides quadradas unidas pela base).
    radius : raio do equador (base das pirâmides)
    ht     : altura do ápice superior acima do equador
    hb     : altura do ápice inferior abaixo do equador
    """
    top = (0.0,    0.0,  ht)
    bot = (0.0,    0.0, -hb)
    # Vértices equatoriais: quadrado a 45° para face de diamante mais limpa
    r45 = radius * 0.7071   # sin/cos 45°
    eq  = [( radius,  0.0, 0.0),
           (  0.0,  radius, 0.0),
           (-radius,  0.0, 0.0),
           (  0.0, -radius, 0.0)]

    faces = []
    for i in range(4):
        a, b = eq[i], eq[(i+1) % 4]
        faces.append((top, a, b))      # pirâmide superior
        faces.append((bot, b, a))      # pirâmide inferior (winding invertido)
    return _geom_from_triangles(faces)


def _build_cylinder(radius, height, segments=20):
    """
    Cilindro sólido centrado na origem com tampas.
    Winding CCW visto de fora em todas as faces.
    """
    hh     = height / 2
    angles = [2 * math.pi * i / segments for i in range(segments)]
    rt     = [(radius * math.cos(a), radius * math.sin(a),  hh) for a in angles]
    rb     = [(radius * math.cos(a), radius * math.sin(a), -hh) for a in angles]
    ct     = (0.0, 0.0,  hh)
    cb     = (0.0, 0.0, -hh)

    faces = []
    for i in range(segments):
        j = (i + 1) % segments
        faces.append((ct, rt[i], rt[j]))          # tampa topo  (+Z)
        faces.append((cb, rb[j], rb[i]))          # tampa base  (−Z)
        faces.append((rb[i], rt[j], rt[i]))       # lateral quad A
        faces.append((rb[i], rb[j], rt[j]))       # lateral quad B

    return _geom_from_triangles(faces)


# ── Classe principal ──────────────────────────────────────────────────────

class GrabbableObject:
    def __init__(self, base, item_type, pos):
        self.base      = base
        self.item_type = item_type
        cfg            = config.ITEMS[item_type]
        self.value     = cfg["value"]

        self.node = base.render.attachNewNode(f"item_{item_type}")
        self.node.setPos(pos[0], pos[1], cfg["ground_z"])

        self._build_geometry(cfg)
        self._build_highlight(cfg)

    # ── Despacho de geometria ──────────────────────────────────────────────

    def _build_geometry(self, cfg):
        color = cfg["color"]
        scale = cfg["scale"]
        shape = cfg["shape"]

        if shape == "necklace":
            self._build_necklace(color)

        elif shape == "trapezoid":
            np = _build_trapezoid_prism(*scale)
            np.reparentTo(self.node)
            np.setColor(*color)

        elif shape == "octahedron":
            np = _build_octahedron(*scale)
            np.reparentTo(self.node)
            np.setColor(*color)
            np.setTransparency(TransparencyAttrib.M_alpha)

        elif shape == "cylinder":
            np = _build_cylinder(*scale)
            np.reparentTo(self.node)
            np.setColor(*color)

        elif shape == "money_bundle":
            self._build_money_bundle(scale, color)

        elif shape == "box":
            np = _build_box(*scale)
            np.reparentTo(self.node)
            np.setColor(*color)

        else:  # sphere (ruby, fallback)
            sph = self.base.loader.loadModel("models/misc/sphere")
            sph.reparentTo(self.node)
            sph.setScale(*scale)
            sph.setColor(*color)

    def _build_money_bundle(self, scale, color):
        """Caixa verde plana + faixa de papel branca ao redor do meio."""
        w, d, h = scale

        main = _build_box(w, d, h)
        main.reparentTo(self.node)
        main.setColor(*color)

        # Faixa de papel: mesma largura/profundidade + 1 % para evitar z-fighting,
        # altura = 22 % do bloco, centrada no meio (z=0)
        band_h  = h * 0.22
        band_np = _build_box(w * 1.012, d * 1.012, band_h)
        band_np.reparentTo(self.node)
        band_np.setColor(0.93, 0.93, 0.88, 1.0)

    def _build_necklace(self, color):
        n  = config.NECKLACE_PEARL_COUNT
        r  = config.NECKLACE_ARC_RADIUS
        pr = config.NECKLACE_PEARL_RADIUS
        for i in range(n):
            angle = math.pi * i / (n - 1)
            pearl = self.base.loader.loadModel("models/misc/sphere")
            pearl.reparentTo(self.node)
            pearl.setScale(pr)
            pearl.setPos(math.cos(angle) * r, math.sin(angle) * r, pr)
            pearl.setColor(*color)

    # ── Highlight pulsante ────────────────────────────────────────────────

    def _build_highlight(self, cfg):
        scale = cfg["scale"]
        shape = cfg["shape"]

        if shape == "necklace":
            hl_r = (config.NECKLACE_ARC_RADIUS + config.NECKLACE_PEARL_RADIUS) \
                   * config.HIGHLIGHT_SCALE_FACTOR
        elif shape == "trapezoid":
            hl_r = scale[0] * config.HIGHLIGHT_SCALE_FACTOR          # hw_bot
        elif shape == "octahedron":
            hl_r = max(scale[0], scale[1]) * config.HIGHLIGHT_SCALE_FACTOR
        elif shape == "cylinder":
            hl_r = scale[0] * config.HIGHLIGHT_SCALE_FACTOR          # radius
        elif shape == "money_bundle":
            hl_r = (scale[0] / 2) * config.HIGHLIGHT_SCALE_FACTOR    # metade da largura
        else:
            hl_r = max(scale) * config.HIGHLIGHT_SCALE_FACTOR

        hl = self.base.loader.loadModel("models/misc/sphere")
        hl.reparentTo(self.node)
        hl.setScale(hl_r)
        hl.setLightOff()
        hl.setTransparency(TransparencyAttrib.M_alpha)
        hl.setColorScale(1.0, 1.0, 0.2, config.HIGHLIGHT_ALPHA_MIN)
        hl.setDepthWrite(False)
        hl.setBin("transparent", 10)
        self.highlight_np = hl

    def update_highlight(self, t):
        lo    = config.HIGHLIGHT_ALPHA_MIN
        hi    = config.HIGHLIGHT_ALPHA_MAX
        alpha = lo + (hi - lo) * (0.5 + 0.5 * math.sin(
            t * config.HIGHLIGHT_PULSE_SPEED * math.tau))
        self.highlight_np.setColorScale(1.0, 1.0, 0.2, alpha)

    # ── Remoção ───────────────────────────────────────────────────────────

    def remove(self):
        self.node.removeNode()
