"""
Sincronizador INMET API → banco de dados.

Chave de identificação de um registro: (codigo, data, hora_utc)
  - data     : string "DD/MM/YYYY"
  - hora_utc : string "HHMM" (ex: "1800")

Lógica:
  - Registro existe no banco → atualiza campos divergentes
  - Registro não existe      → insere
  - Registro da API com todos os campos nulos → ignorado
"""

import sys
import requests
import psycopg
from datetime import datetime, timezone, timedelta

from config import DB_CONNSTR, API_TOKEN, API_BASE_URL, DB_TABLE, FIELD_MAP

BR_TZ = timezone(timedelta(hours=-4))


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def fetch_api(data_ini: str, data_fim: str, codigo: str) -> list[dict]:
    """Retorna lista de registros horários da API para o período e estação."""
    url = f"{API_BASE_URL}/{data_ini}/{data_fim}/{codigo}/{API_TOKEN}"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as e:
        print(f"[ERRO] API retornou {e.response.status_code}: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"[ERRO] Falha ao consultar a API: {e}")
        sys.exit(1)


def is_null_record(api_rec: dict) -> bool:
    """Retorna True se todos os campos meteorológicos do registro são nulos."""
    return all(api_rec.get(k) is None for k in FIELD_MAP)


# ---------------------------------------------------------------------------
# Conversão de formatos
# ---------------------------------------------------------------------------

def api_date_to_db(api_date: str) -> str:
    """Converte "YYYY-MM-DD" (API) → "DD/MM/YYYY" (banco)."""
    return datetime.strptime(api_date, "%Y-%m-%d").strftime("%d/%m/%Y")


def compute_dt_obs(data_db: str, hora_utc: str) -> datetime:
    """
    Constrói o datetime local (UTC-4) a partir de data "DD/MM/YYYY"
    e hora UTC "HHMM".
    """
    d = datetime.strptime(data_db, "%d/%m/%Y")
    h, m = int(hora_utc[:2]), int(hora_utc[2:])
    dt_utc = datetime(d.year, d.month, d.day, h, m, tzinfo=timezone.utc)
    return dt_utc.astimezone(BR_TZ)


def api_rec_to_db_row(api_rec: dict) -> dict:
    """
    Converte um registro da API para o dicionário com os nomes das colunas
    do banco. Inclui todos os campos necessários para INSERT.
    """
    data_db  = api_date_to_db(api_rec["DT_MEDICAO"])
    hora_utc = api_rec["HR_MEDICAO"]
    dt_obs   = compute_dt_obs(data_db, hora_utc)
    lat      = float(api_rec["VL_LATITUDE"])
    lon      = float(api_rec["VL_LONGITUDE"])

    row = {
        "data":      data_db,
        "hora_utc":  hora_utc,
        "codigo":    api_rec["CD_ESTACAO"],
        "nome":      api_rec["DC_NOME"],
        "latitude":  lat,
        "longitude": lon,
        "dt_obs":    dt_obs,
        "dt":        dt_obs,
        # geometry calculada no SQL via ST_SetSRID(ST_MakePoint(lon, lat), 4326)
    }

    for api_field, db_col in FIELD_MAP.items():
        val = api_rec.get(api_field)
        row[db_col] = float(val) if val is not None else None

    return row


# ---------------------------------------------------------------------------
# Banco de dados
# ---------------------------------------------------------------------------

def get_db_records(conn, codigo: str, data_ini: str, data_fim: str) -> dict:
    """
    Busca os registros do banco para o período e estação.
    Retorna dict indexado por (data, hora_utc) → row como dict.

    data_ini / data_fim no formato "YYYY-MM-DD".
    """
    d_ini  = api_date_to_db(data_ini)
    d_fim  = api_date_to_db(data_fim)
    dt_ini = compute_dt_obs(d_ini, "0000")
    dt_fim = compute_dt_obs(d_fim, "0000")

    sql = f"""
        SELECT data, hora_utc,
               {', '.join(FIELD_MAP.values())}
        FROM {DB_TABLE}
        WHERE codigo = %s
          AND dt_obs >= %s
          AND dt_obs <  %s + INTERVAL '1 day'
        ORDER BY data, hora_utc
    """

    result = {}
    with conn.cursor() as cur:
        cur.execute(sql, (codigo, dt_ini, dt_fim))
        cols = [desc[0] for desc in cur.description]
        for row in cur.fetchall():
            rec = dict(zip(cols, row))
            result[(rec["data"], rec["hora_utc"])] = rec
    return result


def update_record(conn, row: dict, existing: dict) -> bool:
    """Atualiza apenas os campos que diferem entre API e banco."""
    diffs = {}
    for db_col in FIELD_MAP.values():
        api_val = row.get(db_col)
        db_val  = existing.get(db_col)
        api_f = float(api_val) if api_val is not None else None
        db_f  = float(db_val)  if db_val  is not None else None
        if api_f != db_f:
            diffs[db_col] = api_val

    if not diffs:
        return False

    set_clause = ", ".join(f"{col} = %s" for col in diffs)
    values = list(diffs.values()) + [row["codigo"], row["data"], row["hora_utc"]]
    sql = f"""
        UPDATE {DB_TABLE}
        SET {set_clause}
        WHERE codigo = %s AND data = %s AND hora_utc = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, values)
    return True


def insert_record(conn, row: dict):
    """Insere um novo registro no banco."""
    cols      = list(row.keys()) + ["geometry"]
    ph_values = ["%s"] * len(row) + ["ST_SetSRID(ST_MakePoint(%s, %s), 4326)"]
    values    = list(row.values()) + [row["longitude"], row["latitude"]]

    sql = f"INSERT INTO {DB_TABLE} ({', '.join(cols)}) VALUES ({', '.join(ph_values)})"
    with conn.cursor() as cur:
        cur.execute(sql, values)


# ---------------------------------------------------------------------------
# Sincronização
# ---------------------------------------------------------------------------

def sync(conn, api_records: list[dict], codigo: str, data_ini: str, data_fim: str):
    db_records = get_db_records(conn, codigo, data_ini, data_fim)
    print(f"  {len(db_records)} registros encontrados no banco para o período.\n")

    inserted = 0
    updated  = 0
    skipped  = 0

    for api_rec in api_records:
        if is_null_record(api_rec):
            skipped += 1
            continue

        row = api_rec_to_db_row(api_rec)
        key = (row["data"], row["hora_utc"])

        if key in db_records:
            if update_record(conn, row, db_records[key]):
                updated += 1
                print(f"  [UPDATE] {key[0]} {key[1]}")
        else:
            insert_record(conn, row)
            inserted += 1
            print(f"  [INSERT] {key[0]} {key[1]}")

    conn.commit()

    print(f"\n{'='*40}")
    print(f"  Inseridos  : {inserted}")
    print(f"  Atualizados: {updated}")
    print(f"  Sem dados (ignorados): {skipped}")
    print(f"{'='*40}")


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------

def input_date(prompt: str) -> str:
    """Solicita uma data no formato YYYY-MM-DD com validação básica."""
    while True:
        val = input(prompt).strip()
        try:
            datetime.strptime(val, "%Y-%m-%d")
            return val
        except ValueError:
            print("  Formato inválido. Use YYYY-MM-DD (ex: 2026-05-07).")


def main():
    print("=" * 40)
    print("  Sincronizador INMET → Banco de Dados")
    print("=" * 40)

    data_ini = input_date("Data inicial (YYYY-MM-DD): ")
    data_fim = input_date("Data final   (YYYY-MM-DD): ")
    codigo   = input("Código da estação (ex: A702): ").strip().upper()

    print(f"\nBuscando na API: estação {codigo} | {data_ini} → {data_fim}")
    api_data = fetch_api(data_ini, data_fim, codigo)
    print(f"  {len(api_data)} registros retornados pela API.")

    with psycopg.connect(DB_CONNSTR) as conn:
        sync(conn, api_data, codigo, data_ini, data_fim)


if __name__ == "__main__":
    main()
