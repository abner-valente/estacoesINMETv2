"""
Sincronizador INMET API → banco de dados.

Chave de identificação de um registro: (codigo, data, hora_utc)
  - data     : tipo DATE (PostgreSQL)
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

TZ_MINUS4 = timezone(timedelta(hours=-4))

from config import DB_CONNSTR, API_TOKEN, API_BASE_URL, DB_TABLE, FIELD_MAP


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

def api_date_to_db(api_date: str):
    """Converte "YYYY-MM-DD" (API) → objeto date do Python (coluna DATE no banco)."""
    return datetime.strptime(api_date, "%Y-%m-%d").date()



def make_id(api_date: str, hora_utc: str, codigo: str) -> str:
    """Gera o id_dado_inmet no padrão YYYYMMDDHHMM_CODIGO (ex: 202605071300_A709)."""
    date_part = datetime.strptime(api_date, "%Y-%m-%d").strftime("%Y%m%d")
    return f"{date_part}{hora_utc}_{codigo}"


def api_rec_to_db_row(api_rec: dict) -> dict:
    """
    Converte um registro da API para o dicionário com os nomes das colunas
    do banco. Inclui todos os campos necessários para INSERT.
    """
    data_db  = api_date_to_db(api_rec["DT_MEDICAO"])
    hora_utc_str = api_rec["HR_MEDICAO"]          # "1400" — usado no id e na chave
    hora_utc_int = int(hora_utc_str)              # 1400  — tipo real da coluna no banco
    codigo       = api_rec["CD_ESTACAO"]
    lat          = float(api_rec["VL_LATITUDE"])
    lon          = float(api_rec["VL_LONGITUDE"])

    h = hora_utc_int // 100
    m = hora_utc_int % 100
    data_hora_obs_utc = datetime(data_db.year, data_db.month, data_db.day, h, m, 0,
                                 tzinfo=TZ_MINUS4)

    row = {
        "id_dado_inmet":     make_id(api_rec["DT_MEDICAO"], hora_utc_str, codigo),
        "data":              data_db,
        "hora_utc":          hora_utc_int,
        "data_hora_obs_utc": data_hora_obs_utc,
        "codigo":    codigo,
        "nome":      api_rec["DC_NOME"],
        "latitude":  lat,
        "longitude": lon,
        # geom calculada no SQL via ST_SetSRID(ST_MakePoint(lon, lat), 4326)
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
    d_ini = datetime.strptime(data_ini, "%Y-%m-%d").date()
    d_fim = datetime.strptime(data_fim, "%Y-%m-%d").date()

    sql = f"""
        SELECT data, hora_utc,
               {', '.join(FIELD_MAP.values())}
        FROM {DB_TABLE}
        WHERE codigo = %s
          AND data BETWEEN %s AND %s
        ORDER BY data, hora_utc
    """

    result = {}
    with conn.cursor() as cur:
        cur.execute(sql, (codigo, d_ini, d_fim))
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
    values = list(diffs.values()) + [row["codigo"], row["data"], int(row["hora_utc"])]
    sql = f"""
        UPDATE {DB_TABLE}
        SET {set_clause}
        WHERE codigo = %s AND data = %s AND hora_utc = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, values)
        if cur.rowcount == 0:
            print(f"  [AVISO] UPDATE executado mas nenhuma linha foi afetada: "
                  f"{row['codigo']} {row['data']} {row['hora_utc']}")
            return False
    return True


def insert_record(conn, row: dict):
    """Insere um novo registro no banco."""
    cols      = list(row.keys()) + ["geom"]
    ph_values = ["%s"] * len(row) + ["ST_SetSRID(ST_MakePoint(%s, %s), 4326)"]
    values    = list(row.values()) + [row["longitude"], row["latitude"]]

    sql = f"INSERT INTO {DB_TABLE} ({', '.join(cols)}) VALUES ({', '.join(ph_values)}) ON CONFLICT DO NOTHING"
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
