-- =====================================================================
-- DATA WAREHOUSE · Modelo dimensional en estrella (constelación de hechos)
-- Motor: SQLite (prototipo académico). Claves sustitutas INTEGER.
-- =====================================================================

-- ---------------------------- DIMENSIONES ----------------------------
CREATE TABLE IF NOT EXISTS dim_fecha (
  fecha_key           INTEGER PRIMARY KEY,          -- AAAAMMDD
  fecha               TEXT NOT NULL UNIQUE,
  dia                 INTEGER NOT NULL,
  dia_semana          INTEGER NOT NULL,             -- 1 = lunes ... 7 = domingo
  nombre_dia          TEXT NOT NULL,
  es_fin_semana       INTEGER NOT NULL,             -- sábado o domingo
  semana_anio         INTEGER NOT NULL,             -- semana ISO
  mes                 INTEGER NOT NULL,
  nombre_mes          TEXT NOT NULL,
  trimestre           INTEGER NOT NULL,
  anio                INTEGER NOT NULL,
  anio_mes            TEXT NOT NULL,                -- AAAA-MM
  temporada           TEXT NOT NULL,                -- Alta / Media / Baja
  es_vacaciones       INTEGER NOT NULL,
  periodo_vacacional  TEXT,
  es_festivo          INTEGER NOT NULL,
  es_festivo_oficial  INTEGER NOT NULL,
  nombre_festivo      TEXT
);

CREATE TABLE IF NOT EXISTS dim_complejo (
  complejo_key     INTEGER PRIMARY KEY AUTOINCREMENT,
  complejo_codigo  TEXT NOT NULL UNIQUE,            -- clave natural
  nombre           TEXT NOT NULL,                   -- nombre ficticio
  ciudad           TEXT NOT NULL,
  estado           TEXT NOT NULL,
  region           TEXT NOT NULL,
  tipo_complejo    TEXT NOT NULL,
  fecha_apertura   TEXT NOT NULL,
  num_salas        INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_sala (
  sala_key      INTEGER PRIMARY KEY AUTOINCREMENT,
  sala_codigo   TEXT NOT NULL UNIQUE,
  complejo_key  INTEGER NOT NULL REFERENCES dim_complejo(complejo_key),
  numero        INTEGER NOT NULL,
  formato       TEXT NOT NULL,
  capacidad     INTEGER NOT NULL CHECK (capacidad > 0)
);

CREATE TABLE IF NOT EXISTS dim_pelicula (
  pelicula_key      INTEGER PRIMARY KEY AUTOINCREMENT,
  pelicula_codigo   TEXT NOT NULL UNIQUE,
  titulo            TEXT NOT NULL,
  genero            TEXT NOT NULL,
  clasificacion     TEXT NOT NULL,
  duracion_min      INTEGER NOT NULL,
  fecha_estreno     TEXT NOT NULL,
  distribuidora     TEXT NOT NULL,
  tipo_lanzamiento  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_horario (
  horario_key            INTEGER PRIMARY KEY,       -- HHMM
  hora                   TEXT NOT NULL UNIQUE,      -- HH:MM
  hora_num               INTEGER NOT NULL,
  turno                  TEXT NOT NULL,             -- Matutino / Vespertino / Nocturno / Trasnoche
  clasificacion_horario  TEXT NOT NULL              -- Valle / Normal / Pico
);

CREATE TABLE IF NOT EXISTS dim_producto (
  producto_key    INTEGER PRIMARY KEY AUTOINCREMENT,
  sku             TEXT NOT NULL UNIQUE,
  nombre          TEXT NOT NULL,
  categoria       TEXT NOT NULL,
  precio_lista    REAL NOT NULL,                    -- vigente (SCD tipo 1)
  costo_unitario  REAL NOT NULL,                    -- costo simulado vigente
  exclusivo_vip   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_canal (
  canal_key       INTEGER PRIMARY KEY AUTOINCREMENT,
  canal_codigo    TEXT NOT NULL UNIQUE,
  nombre          TEXT NOT NULL,
  tipo_canal      TEXT NOT NULL,                    -- Presencial / Digital
  vende_boletos   INTEGER NOT NULL,
  vende_dulceria  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_promocion (
  promocion_key     INTEGER PRIMARY KEY AUTOINCREMENT,
  promocion_codigo  TEXT NOT NULL UNIQUE,
  nombre            TEXT NOT NULL,
  tipo              TEXT NOT NULL,
  descuento_pct     REAL NOT NULL CHECK (descuento_pct BETWEEN 0 AND 1),
  vigencia_inicio   TEXT NOT NULL,
  vigencia_fin      TEXT NOT NULL
);

-- ------------------------------ HECHOS ------------------------------
-- Grano: una función (proyección de una película en una sala, fecha y hora).
CREATE TABLE IF NOT EXISTS fact_funciones (
  funcion_id            INTEGER PRIMARY KEY,        -- dimensión degenerada
  fecha_key             INTEGER NOT NULL REFERENCES dim_fecha(fecha_key),
  complejo_key          INTEGER NOT NULL REFERENCES dim_complejo(complejo_key),
  pelicula_key          INTEGER NOT NULL REFERENCES dim_pelicula(pelicula_key),
  sala_key              INTEGER NOT NULL REFERENCES dim_sala(sala_key),
  horario_key           INTEGER NOT NULL REFERENCES dim_horario(horario_key),
  promocion_key         INTEGER NOT NULL REFERENCES dim_promocion(promocion_key),
  semana_exhibicion     INTEGER NOT NULL,
  capacidad             INTEGER NOT NULL CHECK (capacidad > 0),
  boletos_vendidos      INTEGER NOT NULL CHECK (boletos_vendidos >= 0),
  asistentes            INTEGER NOT NULL CHECK (asistentes >= 0),
  asientos_disponibles  INTEGER NOT NULL CHECK (asientos_disponibles >= 0),
  porcentaje_ocupacion  REAL NOT NULL CHECK (porcentaje_ocupacion BETWEEN 0 AND 100)
);

-- Grano: ventas de boletos de una función por canal de venta.
CREATE TABLE IF NOT EXISTS fact_ventas_boletos (
  venta_id            INTEGER PRIMARY KEY,
  funcion_id          INTEGER NOT NULL,             -- dimensión degenerada
  fecha_key           INTEGER NOT NULL REFERENCES dim_fecha(fecha_key),
  complejo_key        INTEGER NOT NULL REFERENCES dim_complejo(complejo_key),
  pelicula_key        INTEGER NOT NULL REFERENCES dim_pelicula(pelicula_key),
  sala_key            INTEGER NOT NULL REFERENCES dim_sala(sala_key),
  horario_key         INTEGER NOT NULL REFERENCES dim_horario(horario_key),
  canal_key           INTEGER NOT NULL REFERENCES dim_canal(canal_key),
  promocion_key       INTEGER NOT NULL REFERENCES dim_promocion(promocion_key),
  boletos_vendidos    INTEGER NOT NULL CHECK (boletos_vendidos > 0),
  precio_unitario     REAL NOT NULL CHECK (precio_unitario > 0),
  descuento_unitario  REAL NOT NULL CHECK (descuento_unitario >= 0),
  monto_descuento     REAL NOT NULL,
  ingreso_total       REAL NOT NULL CHECK (ingreso_total >= 0),
  UNIQUE (funcion_id, canal_key)
);

-- Grano: unidades de un producto vendidas en un complejo, en un día y por un canal.
CREATE TABLE IF NOT EXISTS fact_ventas_dulceria (
  fecha_key          INTEGER NOT NULL REFERENCES dim_fecha(fecha_key),
  complejo_key       INTEGER NOT NULL REFERENCES dim_complejo(complejo_key),
  producto_key       INTEGER NOT NULL REFERENCES dim_producto(producto_key),
  canal_key          INTEGER NOT NULL REFERENCES dim_canal(canal_key),
  unidades_vendidas  INTEGER NOT NULL CHECK (unidades_vendidas > 0),
  precio_unitario    REAL NOT NULL CHECK (precio_unitario > 0),
  costo_unitario     REAL NOT NULL CHECK (costo_unitario >= 0),
  ingreso_total      REAL NOT NULL,
  costo_total        REAL NOT NULL,
  margen_bruto       REAL NOT NULL,
  PRIMARY KEY (fecha_key, complejo_key, producto_key, canal_key)
);

CREATE INDEX IF NOT EXISTS ix_ff_fecha ON fact_funciones(fecha_key);
CREATE INDEX IF NOT EXISTS ix_ff_complejo ON fact_funciones(complejo_key, fecha_key);
CREATE INDEX IF NOT EXISTS ix_ff_pelicula ON fact_funciones(pelicula_key);
CREATE INDEX IF NOT EXISTS ix_fb_fecha ON fact_ventas_boletos(fecha_key);
CREATE INDEX IF NOT EXISTS ix_fb_complejo ON fact_ventas_boletos(complejo_key, fecha_key);
CREATE INDEX IF NOT EXISTS ix_fb_pelicula ON fact_ventas_boletos(pelicula_key);
CREATE INDEX IF NOT EXISTS ix_fd_complejo ON fact_ventas_dulceria(complejo_key, fecha_key);
CREATE INDEX IF NOT EXISTS ix_fd_producto ON fact_ventas_dulceria(producto_key);

-- ---------------------------- DATA MARTS ----------------------------
-- Mart ejecutivo: un complejo en un día (alimenta el dashboard y el modelo predictivo).
CREATE TABLE IF NOT EXISTS mart_diario_complejo (
  fecha_key            INTEGER NOT NULL REFERENCES dim_fecha(fecha_key),
  complejo_key         INTEGER NOT NULL REFERENCES dim_complejo(complejo_key),
  funciones            INTEGER NOT NULL,
  capacidad            INTEGER NOT NULL,
  boletos              INTEGER NOT NULL,
  asistentes           INTEGER NOT NULL,
  ingreso_taquilla     REAL NOT NULL,
  descuentos           REAL NOT NULL,
  ingreso_dulceria     REAL NOT NULL,
  costo_dulceria       REAL NOT NULL,
  unidades_dulceria    INTEGER NOT NULL,
  peliculas_exhibidas  INTEGER NOT NULL,
  estrenos_exhibidos   INTEGER NOT NULL,
  PRIMARY KEY (fecha_key, complejo_key)
);

-- Mart de taquilla: mes x complejo x película.
CREATE TABLE IF NOT EXISTS mart_pelicula_mensual (
  anio_mes          TEXT NOT NULL,
  complejo_key      INTEGER NOT NULL REFERENCES dim_complejo(complejo_key),
  pelicula_key      INTEGER NOT NULL REFERENCES dim_pelicula(pelicula_key),
  funciones         INTEGER NOT NULL,
  capacidad         INTEGER NOT NULL,
  boletos           INTEGER NOT NULL,
  asistentes        INTEGER NOT NULL,
  ingreso_taquilla  REAL NOT NULL,
  PRIMARY KEY (anio_mes, complejo_key, pelicula_key)
);

-- Mart de canales y formatos: mes x complejo x sala x canal x promoción.
CREATE TABLE IF NOT EXISTS mart_taquilla_mensual (
  anio_mes       TEXT NOT NULL,
  complejo_key   INTEGER NOT NULL REFERENCES dim_complejo(complejo_key),
  sala_key       INTEGER NOT NULL REFERENCES dim_sala(sala_key),
  canal_key      INTEGER NOT NULL REFERENCES dim_canal(canal_key),
  promocion_key  INTEGER NOT NULL REFERENCES dim_promocion(promocion_key),
  boletos        INTEGER NOT NULL,
  ingreso        REAL NOT NULL,
  descuentos     REAL NOT NULL,
  PRIMARY KEY (anio_mes, complejo_key, sala_key, canal_key, promocion_key)
);

-- Mart de dulcería: mes x complejo x producto x canal.
CREATE TABLE IF NOT EXISTS mart_dulceria_mensual (
  anio_mes      TEXT NOT NULL,
  complejo_key  INTEGER NOT NULL REFERENCES dim_complejo(complejo_key),
  producto_key  INTEGER NOT NULL REFERENCES dim_producto(producto_key),
  canal_key     INTEGER NOT NULL REFERENCES dim_canal(canal_key),
  unidades      INTEGER NOT NULL,
  ingreso       REAL NOT NULL,
  costo         REAL NOT NULL,
  margen        REAL NOT NULL,
  PRIMARY KEY (anio_mes, complejo_key, producto_key, canal_key)
);

-- --------------------------- CONTROL DEL ETL ---------------------------
CREATE TABLE IF NOT EXISTS etl_ejecucion (
  run_id               INTEGER PRIMARY KEY AUTOINCREMENT,
  inicio               TEXT NOT NULL,
  fin                  TEXT,
  duracion_seg         REAL,
  modo                 TEXT NOT NULL,              -- completa / incremental
  archivos_procesados  INTEGER DEFAULT 0,
  extraidos            INTEGER DEFAULT 0,
  transformados        INTEGER DEFAULT 0,
  cargados             INTEGER DEFAULT 0,
  rechazados           INTEGER DEFAULT 0,
  corregidos           INTEGER DEFAULT 0,
  estado               TEXT NOT NULL,              -- EN PROCESO / EXITOSO / SIN CAMBIOS / ERROR
  mensaje              TEXT,
  detalle              TEXT                        -- JSON con conteos por fuente
);

CREATE TABLE IF NOT EXISTS etl_archivo (
  archivo    TEXT PRIMARY KEY,
  checksum   TEXT NOT NULL,
  filas      INTEGER NOT NULL,
  run_id     INTEGER NOT NULL,
  cargado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS etl_rechazo (
  rechazo_id  INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id      INTEGER NOT NULL,
  fuente      TEXT NOT NULL,
  archivo     TEXT NOT NULL,
  motivo      TEXT NOT NULL,
  registro    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_rechazo_run ON etl_rechazo(run_id);
