import os
from dotenv import load_dotenv

load_dotenv()

DB_CONNSTR = (
    f"host={os.getenv('s1875_POSTGRES_HOST')} "
    f"port={os.getenv('s1875_POSTGRES_PORT')} "
    f"dbname={os.getenv('s1875_POSTGRES_NAME')} "
    f"user={os.getenv('s1875_POSTGRES_USER')} "
    f"password={os.getenv('s1875_POSTGRES_PASSWORD')}"
)

API_TOKEN = os.getenv("INMET_API_TOKEN")
API_BASE_URL = os.getenv("INMET_API_BASE_URL", "https://apitempo.inmet.gov.br/token/estacao")

DB_TABLE = os.getenv("DB_TABLE", "schema.inmet_dados")

# Mapeamento campos API → colunas do banco
FIELD_MAP = {
    "TEM_INS": "temp_ins_c",
    "TEM_MAX": "temp_max_c",
    "TEM_MIN": "temp_min_c",
    "UMD_INS": "umid_ins_pct",
    "UMD_MAX": "umid_max_pct",
    "UMD_MIN": "umid_min_pct",
    "PTO_INS": "pto_orvalho_ins_c",
    "PTO_MAX": "pto_orvalho_max_c",
    "PTO_MIN": "pto_orvalho_min_c",
    "PRE_INS": "press_ins_hpa",
    "PRE_MAX": "press_max_hpa",
    "PRE_MIN": "press_min_hpa",
    "VEN_VEL": "vel_vento_ms",
    "VEN_DIR": "dir_vento_graus",
    "VEN_RAJ": "raj_vento_ms",
    "RAD_GLO": "radiacao_kj_m2",
    "CHUVA":   "chuva_mm",
}
