# Configuração centralizada do Shadow Heist

# ── Câmera ───────────────────────────────────────────────────────────────
CAM_DIST_MAX           = 20.0
CAM_DIST_MIN           =  5.0
FLOATER_Z_OFFSET       =  2.0
CAM_PITCH_DEFAULT      = 20.0
CAM_PITCH_MIN          =  5.0
CAM_PITCH_MAX          = 75.0
CAM_PITCH_CROUCH       = -8.0
CAM_PITCH_SPEED        = 60.0
CAM_ZOOM_SPEED         = 10.0
MOUSE_SENS             =  0.25

# ── Movimento ────────────────────────────────────────────────────────────
WALK_SPEED             = 12.0
TURN_SPEED             = 200.0
CROUCH_SPEED_MULT      =  0.45
CROUCH_TRANSITION_TIME =  0.08
SQUISH_SPEED           =  9.0

# ── Animação procedural (frequências do squish) ──────────────────────────
ANIM_IDLE_FREQ         =  1.2   # rad/s — respiração lenta do slime parado
ANIM_WALK_FREQ         =  8.0   # rad/s — bounce de passada (~2 passos/s via abs(sin))
ANIM_CRAWL_FREQ        =  6.0   # rad/s — ondulação do crouch-walk

# ── Pulo ─────────────────────────────────────────────────────────────────
JUMP_SPEED             = 10.0
GRAVITY                = 28.0
GROUND_LEVEL           =  1.1   # raio base da CollisionSphere (= z mínimo do player)

# ── Grab (animação) ──────────────────────────────────────────────────────
GRAB_T1_TIME           = 0.05
GRAB_T2_TIME           = 0.05
GRAB_HOLD_TIME         = 0.07
GRAB_RANGE             = 3.5    # distância máxima para coletar item

# ── Camuflagem ───────────────────────────────────────────────────────────
CAMO_ALPHA             = 0.22
CAMO_DURATION          = 1.0
CAMO_COOLDOWN          = 8.0

# ── Crescimento do player ────────────────────────────────────────────────
GROWTH_PER_VALUE_UNIT  = 0.001  # acréscimo de escala por ponto de valor do item
MAX_GROWTH_SCALE       = 2.0    # escala máxima atingível

# ── Velocidade × Tamanho ─────────────────────────────────────────────────
# speed_efetiva = WALK_SPEED / growth_scale ^ SPEED_SCALE_EXPONENT
SPEED_SCALE_EXPONENT   = 0.6

# ── Highlight dos itens ──────────────────────────────────────────────────
HIGHLIGHT_PULSE_SPEED  = 2.5    # Hz do pulso de alpha
HIGHLIGHT_ALPHA_MIN    = 0.15
HIGHLIGHT_ALPHA_MAX    = 0.55
HIGHLIGHT_SCALE_FACTOR = 1.10   # raio do halo = maior dimensão do item × este fator

# ── Colar de pérolas ─────────────────────────────────────────────────────
NECKLACE_PEARL_COUNT   = 9
NECKLACE_ARC_RADIUS    = 0.55
NECKLACE_PEARL_RADIUS  = 0.12

# ── Definição dos itens interagíveis ─────────────────────────────────────
# shape: "trapezoid" | "octahedron" | "cylinder" | "money_bundle"
#        "sphere" | "necklace"
# scale (por shape):
#   trapezoid    → (hw_bot, hd_bot, height)   ground_z = height/2
#   octahedron   → (radius, ht, hb)           ground_z = hb
#   cylinder     → (radius, height)           ground_z = height/2
#   money_bundle → (w, d, h)                  ground_z = h/2
#   sphere       → (sx, sy, sz)               ground_z = sz
#   necklace     → ignorado                   ground_z = 0
ITEMS = {
    "gold_bar": {
        "value":    100,
        "color":    (1.00, 0.85, 0.08, 1.0),
        "shape":    "trapezoid",
        "scale":    (0.80, 0.40, 0.40),   # hw_bot, hd_bot, height
        "ground_z":  0.20,
    },
    "diamond": {
        "value":     80,
        "color":    (0.60, 0.95, 1.00, 0.72),
        "shape":    "octahedron",
        "scale":    (0.30, 0.38, 0.16),   # radius, ht, hb
        "ground_z":  0.16,
    },
    "pearl_necklace": {
        "value":     60,
        "color":    (0.98, 0.98, 0.95, 1.0),
        "shape":    "necklace",
        "scale":    (1.0,  1.0,  1.0),
        "ground_z":  0.0,
    },
    "money_bundle": {
        "value":     40,
        "color":    (0.12, 0.72, 0.14, 1.0),
        "shape":    "money_bundle",
        "scale":    (1.00, 0.50, 0.45),   # w, d, h
        "ground_z":  0.225,
    },
    "ruby": {
        "value":     50,
        "color":    (0.85, 0.02, 0.02, 1.0),
        "shape":    "sphere",
        "scale":    (0.45, 0.45, 0.22),   # cabochon: largo e baixo
        "ground_z":  0.22,
    },
    "coin_pile": {
        "value":     20,
        "color":    (1.00, 0.78, 0.00, 1.0),
        "shape":    "cylinder",
        "scale":    (0.55, 0.18),          # radius, height
        "ground_z":  0.09,
    },
}
