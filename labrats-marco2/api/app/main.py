"""API do LabRats (Marco 2). Endpoints síncronos: o FastAPI os executa em um pool de threads."""
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import seed, timeutil
from .cassandra_store import CassandraStore
from .mongo_store import MongoStore
from .redis_store import RedisStore
from .service import Servico

S: Servico


@asynccontextmanager
async def lifespan(app: FastAPI):
    global S
    redis, cass, mongo = RedisStore(), CassandraStore(), MongoStore()
    mongo.init()
    cass.conectar()
    S = Servico(redis, cass, mongo)
    yield


app = FastAPI(title="LabRats — Marco 2", lifespan=lifespan)


# ---------------- modelos ----------------
class CheckinIn(BaseModel):
    aluno_id: int
    academia_id: int


class Metrica(BaseModel):
    chave: str = Field(pattern=r"^[a-z0-9_]{2,30}$")
    nome: str
    unidade: str = ""
    modo: Literal["maximo", "queda", "ganho"]


class GrupoIn(BaseModel):
    nome: str = Field(min_length=3, max_length=80)
    descricao: str = ""
    criador_id: int
    metricas: list[Metrica] = Field(min_length=1, max_length=10)


class MembroIn(BaseModel):
    aluno_id: int


class RegistroIn(BaseModel):
    aluno_id: int
    valores: dict[str, float] = Field(min_length=1)
    data: date | None = None


# ---------------- util ----------------
@app.get("/", include_in_schema=False)
def home():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/health")
def health():
    def tenta(f):
        try:
            return "ok" if f() else "falha"
        except Exception as e:     # noqa: BLE001
            return f"falha: {e.__class__.__name__}"
    return {"redis": tenta(S.redis.ping), "cassandra": tenta(S.cass.ping), "mongodb": tenta(S.mongo.ping),
            "fila_de_falhas": S.redis.dlq_tamanho()}


@app.get("/academias")
def academias():
    return S.mongo.academias()


@app.get("/alunos")
def alunos():
    return S.mongo.alunos()


@app.post("/checkin")
def checkin(corpo: CheckinIn, bg: BackgroundTasks):
    if not S.mongo.aluno(corpo.aluno_id):
        raise HTTPException(404, "Aluno não encontrado")
    if not S.mongo.academia_existe(corpo.academia_id):
        raise HTTPException(404, "Academia não encontrada")
    return S.fazer_checkin(corpo.aluno_id, corpo.academia_id, bg)


@app.post("/checkout/{aluno_id}")
def checkout(aluno_id: int):
    r = S.fazer_checkout(aluno_id)
    if not r:
        raise HTTPException(404, "Aluno sem check-in ativo")
    return r


@app.get("/alunos/{aluno_id}/streak")
def streak(aluno_id: int):
    return S.streak(aluno_id)


@app.get("/alunos/{aluno_id}/historico")
def historico(aluno_id: int, limite: int = Query(20, le=100)):
    return S.cass.historico_aluno(aluno_id, limite)


@app.get("/academias/{academia_id}/ranking")
def ranking(academia_id: int, semana: str | None = None, topo: int = Query(10, le=50)):
    return S.ranking(academia_id, semana, topo)


@app.get("/academias/{academia_id}/painel")
def painel(academia_id: int, de: date | None = None, ate: date | None = None):
    ate = ate or timeutil.agora().date()
    de = de or ate - timedelta(days=6)
    if de > ate or (ate - de).days > 31:
        raise HTTPException(400, "Intervalo inválido (máximo de 31 dias)")
    return S.painel(academia_id, de, ate)


@app.post("/grupos", status_code=201)
def criar_grupo(corpo: GrupoIn):
    nome = S.mongo.aluno(corpo.criador_id)
    if not nome:
        raise HTTPException(404, "Criador não encontrado")
    gid = S.mongo.criar_grupo(corpo.model_dump())
    S.mongo.adicionar_membro(gid, corpo.criador_id, nome["nome"])
    return {"id": gid}


@app.get("/grupos")
def listar_grupos():
    return S.mongo.listar_grupos()


@app.get("/grupos/{grupo_id}")
def ver_grupo(grupo_id: str):
    g = S.mongo.grupo(grupo_id)
    if not g:
        raise HTTPException(404, "Grupo não encontrado")
    return g


@app.post("/grupos/{grupo_id}/membros", status_code=201)
def entrar_no_grupo(grupo_id: str, corpo: MembroIn):
    aluno = S.mongo.aluno(corpo.aluno_id)
    if not aluno or not S.mongo.grupo(grupo_id):
        raise HTTPException(404, "Grupo ou aluno não encontrado")
    if not S.mongo.adicionar_membro(grupo_id, corpo.aluno_id, aluno["nome"]):
        raise HTTPException(409, "Aluno já é membro")
    return {"status": "ok"}


@app.post("/grupos/{grupo_id}/registros", status_code=201)
def registrar(grupo_id: str, corpo: RegistroIn):
    g = S.mongo.grupo(grupo_id)
    if not g:
        raise HTTPException(404, "Grupo não encontrado")
    if corpo.aluno_id not in {m["aluno_id"] for m in g["membros"]}:
        raise HTTPException(403, "Aluno não é membro do grupo")
    validas = {m["chave"] for m in g["metricas"]}
    estranhas = set(corpo.valores) - validas
    if estranhas:
        raise HTTPException(422, f"Métricas fora do grupo: {sorted(estranhas)}")
    return {"id": S.mongo.registrar_medidas(grupo_id, corpo.aluno_id, corpo.data or timeutil.agora().date(),
                                            corpo.valores)}


@app.get("/grupos/{grupo_id}/placar")
def placar(grupo_id: str):
    g = S.mongo.grupo(grupo_id)
    if not g:
        raise HTTPException(404, "Grupo não encontrado")
    return {"grupo": g["nome"], "placar": S.mongo.placar(g)}


@app.post("/admin/seed")
def admin_seed():
    return seed.popular(S)


@app.post("/admin/reconstruir/{academia_id}")
def admin_reconstruir(academia_id: int):
    """Mostra a vantagem de ter o Cassandra como fonte da verdade: o Redis pode ser refeito."""
    return S.reconstruir(academia_id)


@app.post("/admin/reprocessar-fila")
def admin_reprocessar():
    return S.reprocessar_fila()
