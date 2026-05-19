import os
import requests
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DB_CONNSTR = (
    f"host={os.getenv('s1875_POSTGRES_HOST')} "
    f"port={os.getenv('s1875_POSTGRES_PORT')} "
    f"dbname={os.getenv('s1875_POSTGRES_NAME')} "
    f"user={os.getenv('s1875_POSTGRES_USER')} "
    f"password={os.getenv('s1875_POSTGRES_PASSWORD')}"
)

API_URL = "https://apitempo.inmet.gov.br/estacoes/M"

INSERT_SQL = """
    INSERT INTO tb_estacoes_inmet_manuais (
        CD_OSCAR, DC_NOME, FL_CAPITAL, DT_FIM_OPERACAO, CD_SITUACAO,
        TP_ESTACAO, VL_LATITUDE, CD_WSI, CD_DISTRITO, VL_ALTITUDE,
        SG_ESTADO, SG_ENTIDADE, CD_ESTACAO, VL_LONGITUDE, DT_INICIO_OPERACAO
    ) VALUES (
        %(CD_OSCAR)s, %(DC_NOME)s, %(FL_CAPITAL)s, %(DT_FIM_OPERACAO)s, %(CD_SITUACAO)s,
        %(TP_ESTACAO)s, %(VL_LATITUDE)s, %(CD_WSI)s, %(CD_DISTRITO)s, %(VL_ALTITUDE)s,
        %(SG_ESTADO)s, %(SG_ENTIDADE)s, %(CD_ESTACAO)s, %(VL_LONGITUDE)s, %(DT_INICIO_OPERACAO)s
    )
    ON CONFLICT (CD_ESTACAO) DO NOTHING
"""


def fetch_estacoes():
    print(f"Buscando estações em {API_URL} ...")
    response = requests.get(API_URL, timeout=30)
    response.raise_for_status()
    data = response.json()
    print(f"{len(data)} estações recebidas.")
    return data


def build_row(est):
    return {
        "CD_OSCAR":            est.get("CD_OSCAR"),
        "DC_NOME":             est.get("DC_NOME"),
        "FL_CAPITAL":          (est.get("FL_CAPITAL") or "N")[0],
        "DT_FIM_OPERACAO":     est.get("DT_FIM_OPERACAO"),
        "CD_SITUACAO":         est.get("CD_SITUACAO"),
        "TP_ESTACAO":          est.get("TP_ESTACAO"),
        "VL_LATITUDE":         est.get("VL_LATITUDE"),
        "CD_WSI":              est.get("CD_WSI"),
        "CD_DISTRITO":         (est.get("CD_DISTRITO") or "").strip() or None,
        "VL_ALTITUDE":         est.get("VL_ALTITUDE"),
        "SG_ESTADO":           est.get("SG_ESTADO"),
        "SG_ENTIDADE":         est.get("SG_ENTIDADE"),
        "CD_ESTACAO":          est.get("CD_ESTACAO"),
        "VL_LONGITUDE":        est.get("VL_LONGITUDE"),
        "DT_INICIO_OPERACAO":  est.get("DT_INICIO_OPERACAO"),
    }


def insert_estacoes(estacoes):
    conn = psycopg2.connect(DB_CONNSTR)
    try:
        with conn:
            with conn.cursor() as cur:
                inserted = 0
                skipped = 0
                for est in estacoes:
                    row = build_row(est)
                    cur.execute(INSERT_SQL, row)
                    if cur.rowcount:
                        inserted += 1
                    else:
                        skipped += 1
        print(f"Concluído: {inserted} inseridas, {skipped} ignoradas (já existiam).")
    finally:
        conn.close()


if __name__ == "__main__":
    estacoes = fetch_estacoes()
    insert_estacoes(estacoes)
