# Configuração centralizada do Shadow Heist

# ── Câmera ───────────────────────────────────────────────────────────────
CAM_DIST_MAX           = 12.0
CAM_DIST_MIN           =  1.8
# Auto-follow disabled; mouse drives yaw exclusively. Set >0 to re-enable.
CAM_FOLLOW_FACTOR      =  0.0
# Vertical offset of the camera pivot above the player's feet (head height).
CAM_PIVOT_Z            =  2.0
# How fast the player rotates to face the movement direction (deg / sec).
PLAYER_TURN_LERP       = 720.0
FLOATER_Z_OFFSET       =  2.0
CAM_PITCH_DEFAULT      = 20.0
CAM_PITCH_MIN          =  5.0
CAM_PITCH_MAX          = 75.0
SKYLOOK_AIM_LIFT       = 28.0    # how far up the lookAt point shifts while skylook held
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
WALK_HOP_AMPLITUDE     =  0.45   # vertical hop offset on each step (units)
WALK_LEAN_DEG          =  6.0    # forward/back tilt amplitude during walk
CRAWL_HOP_AMPLITUDE    =  0.10   # subtle bob while crawling

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
# Daylight debug mode: bright flat lighting so the layout is readable.
# Flip to False to restore night-mansion atmosphere.
DAYLIGHT_MODE          = False

# Night-fog density (exponential, per world unit). 0 disables fog.
NIGHT_FOG_DENSITY      = 0.010
NIGHT_FOG_COLOR        = (0.025, 0.030, 0.050)

# Moon disc parameters used by the skybox shader.
MOON_DIR               = (0.55, -0.30, 0.78)   # world-space direction TO moon
MOON_DISC_SIZE         = 0.030                  # angular radius in skybox uv
MOON_COLOR             = (0.85, 0.88, 1.00)
NEBULA_TINT            = (0.22, 0.18, 0.45)

CAMO_ALPHA             = 0.22
CAMO_DURATION          = 1.0   # legacy; pool now governs duration
CAMO_COOLDOWN          = 8.0   # legacy

# ── Stealth power (pool driven by pickups) ───────────────────────────────
STEALTH_POWER_MAX        = 100.0
STEALTH_POWER_START      = 35.0
STEALTH_DRAIN_PER_SEC    = 22.0   # power/sec while camouflaged
STEALTH_MIN_TO_ACTIVATE  = 5.0    # need at least this much to engage
STEALTH_PICKUP_VALUE     = 28.0   # power per orb collected

# Interacao e cenario
INTERACT_RANGE         = 4.0
HOUSE_LAYOUT_SCALE     = 2.6

# ── Crescimento do player ────────────────────────────────────────────────
GROWTH_PER_VALUE_UNIT  = 0.001  # acréscimo de escala por ponto de valor do item
MAX_GROWTH_SCALE       = 2.0    # escala máxima atingível

# ── Velocidade × Tamanho ─────────────────────────────────────────────────
# speed_efetiva = WALK_SPEED / growth_scale ^ SPEED_SCALE_EXPONENT
SPEED_SCALE_EXPONENT   = 0.6

# ── Beholders (inimigos) ────────────────────────────────────────────────
BEHOLDER_COUNT                  = 8
BEHOLDER_HOVER_Z                = 2.4
BEHOLDER_COLLISION_RADIUS       = 1.0
BEHOLDER_MOVE_MAX_STEP          = 0.35
BEHOLDER_BOB_FREQ               = 1.6     # rad/s
BEHOLDER_BOB_AMPL               = 0.18
BEHOLDER_PATROL_SPEED           = 3.5
BEHOLDER_CHASE_SPEED            = 7.0
BEHOLDER_TURN_SPEED             = 220.0   # deg/s
BEHOLDER_SCAN_FREQ              = 0.9     # rad/s
BEHOLDER_SCAN_AMPL_RAD          = 0.6
BEHOLDER_SIGHT_RANGE            = 14.0
BEHOLDER_SIGHT_FOV_DEG          = 95.0
BEHOLDER_CAMO_RANGE_MULT        = 0.35    # range when player is camouflaged
BEHOLDER_CAMO_DETECT_MULT       = 0.45    # detection-fill rate when camo
BEHOLDER_DETECT_GAIN            = 1.6     # per second while seen
BEHOLDER_DETECT_DECAY           = 0.5     # per second while unseen
BEHOLDER_SUSPICIOUS_THRESHOLD   = 0.35
BEHOLDER_SEARCH_TIME            = 5.0     # how long to chase last-seen pos
BEHOLDER_CATCH_RADIUS           = 1.8

# ── Heist (objetivo) ────────────────────────────────────────────────────
HEIST_EXIT_POS                  = (0.0, -56.0)   # south of castle, near spawn area
HEIST_EXIT_RADIUS               = 4.0

# ── Story / relic shards ────────────────────────────────────────────────
SHARD_COUNT                     = 3
SHARD_PICKUP_RADIUS             = 2.2
SHARD_NAMES = [
    "Shard of Echoes",
    "Shard of Veils",
    "Shard of Embers",
]
SHARD_COLORS = [
    (0.30, 0.70, 1.00, 1.0),
    (0.65, 0.30, 1.00, 1.0),
    (1.00, 0.40, 0.20, 1.0),
]
SHARD_BOB_AMPLITUDE             = 0.25
SHARD_BOB_SPEED                 = 1.4
SHARD_SPIN_SPEED                = 60.0  # deg / sec

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
        "color":    (0.9, 0.05, 0.2, 0.8),
        "shape":    "gem",
        "scale":    (0.4, 0.25, 0.45),
        "ground_z":  0.45,
    },
    "coin_pile": {
        "value":     20,
        "color":    (1.00, 0.78, 0.00, 1.0),
        "shape":    "cylinder",
        "scale":    (0.55, 0.18),          # radius, height
        "ground_z":  0.09,
    },
    "stealth_orb": {
        "value":    STEALTH_PICKUP_VALUE,
        "color":    (0.30, 0.85, 1.00, 0.85),
        "shape":    "sphere",
        "scale":    (0.32, 0.32, 0.32),
        "ground_z":  0.55,
    },
}
