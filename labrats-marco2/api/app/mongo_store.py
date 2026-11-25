"""MongoDB — dados semiestruturados e mutáveis: perfil, academias, grupos de disputa e medidas."""
from datetime import date, datetime

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ASCENDING, MongoClient
from pymongo.errors import CollectionInvalid

from . import config

VALIDADOR_REGISTROS = {"$jsonSchema": {
    "bsonType": "object",
    "required": ["grupo_id", "aluno_id", "data", "valores"],
    "properties": {"aluno_id": {"bsonType": "int"}, "valores": {"bsonType": "object"}}}}


def _oid(valor: str) -> ObjectId | None:
    try:
        return ObjectId(valor)
    except (InvalidId, TypeError):
        return None


def _ser(doc: dict) -> dict:
    """ObjectId/datetime -> JSON."""
    out = {}
    for k, v in doc.items():
        if k == "_id":
            out["id"] = str(v)
        elif isinstance(v, ObjectId):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, list):
            out[k] = [_ser(i) if isinstance(i, dict) else i for i in v]
        elif isinstance(v, dict):
            out[k] = _ser(v)
        else:
            out[k] = v
    return out


class MongoStore:
    def __init__(self):
        self.client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=5000)
        self.db = self.client[config.MONGO_DB]
        self._cache_alunos: dict[int, dict] = {}
        self._cache_academias: set[int] = set()

    def init(self):
        try:  
            self.db.create_collection("registros", validator=VALIDADOR_REGISTROS)
        except CollectionInvalid:
            pass
        self.db.registros.create_index([("grupo_id", ASCENDING), ("aluno_id", ASCENDING), ("data", ASCENDING)])
        self.db.grupos.create_index([("membros.aluno_id", ASCENDING)])
        self.db.alunos.create_index([("academia_id", ASCENDING)])

    def ping(self) -> bool:
        return self.client.admin.command("ping").get("ok") == 1.0

    def academias(self) -> list[dict]:
        return [_ser(d) for d in self.db.academias.find().sort("_id")]

    def alunos(self) -> list[dict]:
        return [_ser(d) for d in self.db.alunos.find().sort("_id")]

    def aluno(self, aluno_id: int) -> dict | None:
        if aluno_id in self._cache_alunos:       
            return self._cache_alunos[aluno_id]
        d = self.db.alunos.find_one({"_id": aluno_id})
        if d:
            self._cache_alunos[aluno_id] = _ser(d)
        return self._cache_alunos.get(aluno_id)

    def academia_existe(self, academia_id: int) -> bool:
        if academia_id in self._cache_academias:   
            return True
        if self.db.academias.count_documents({"_id": academia_id}, limit=1) == 1:
            self._cache_academias.add(academia_id)
            return True
        return False

    def nomes(self, ids: list[int]) -> dict[int, str]:
        return {d["_id"]: d["nome"] for d in self.db.alunos.find({"_id": {"$in": ids}}, {"nome": 1})}

    def alunos_da_academia(self, academia_id: int) -> list[int]:
        return [d["_id"] for d in self.db.alunos.find({"academia_id": academia_id}, {"_id": 1})]

    # ---- grupos de disputa ----
    def criar_grupo(self, doc: dict) -> str:
        doc["criado_em"] = datetime.utcnow()
        doc.setdefault("membros", [])
        return str(self.db.grupos.insert_one(doc).inserted_id)

    def listar_grupos(self) -> list[dict]:
        return [_ser(d) for d in self.db.grupos.find().sort("criado_em", -1)]

    def grupo(self, grupo_id: str) -> dict | None:
        oid = _oid(grupo_id)
        d = self.db.grupos.find_one({"_id": oid}) if oid else None
        return _ser(d) if d else None

    def adicionar_membro(self, grupo_id: str, aluno_id: int, nome: str) -> bool:
        r = self.db.grupos.update_one(
            {"_id": _oid(grupo_id), "membros.aluno_id": {"$ne": aluno_id}},   # não duplica
            {"$push": {"membros": {"aluno_id": aluno_id, "nome": nome, "entrou_em": datetime.utcnow()}}})
        return r.modified_count == 1

    def registrar_medidas(self, grupo_id: str, aluno_id: int, data_: date, valores: dict) -> str:
        r = self.db.registros.insert_one({
            "grupo_id": _oid(grupo_id), "aluno_id": aluno_id,
            "data": datetime(data_.year, data_.month, data_.day), "valores": valores})
        return str(r.inserted_id)

    def placar(self, grupo: dict) -> list[dict]:
        """Um ranking por métrica. Cada grupo define suas próprias métricas (esquema flexível)."""
        gid = _oid(grupo["id"])
        saida = []
        for m in grupo.get("metricas", []):
            campo = f"valores.{m['chave']}"
            pipeline = [
                {"$match": {"grupo_id": gid, campo: {"$exists": True}}},
                {"$sort": {"data": 1}},
                {"$group": {"_id": "$aluno_id", "primeiro": {"$first": f"${campo}"},
                            "ultimo": {"$last": f"${campo}"}, "maximo": {"$max": f"${campo}"},
                            "registros": {"$sum": 1}}},
            ]
            linhas = []
            for d in self.db.registros.aggregate(pipeline):
                if m["modo"] == "maximo":
                    score = d["maximo"]
                elif m["modo"] == "queda":
                    score = d["primeiro"] - d["ultimo"]
                else:   # ganho
                    score = d["ultimo"] - d["primeiro"]
                linhas.append({"aluno_id": d["_id"], "score": round(score, 2), "primeiro": d["primeiro"],
                               "ultimo": d["ultimo"], "registros": d["registros"]})
            linhas.sort(key=lambda x: x["score"], reverse=True)
            nomes = {mb["aluno_id"]: mb["nome"] for mb in grupo.get("membros", [])}
            for i, l in enumerate(linhas, 1):
                l["posicao"] = i
                l["nome"] = nomes.get(l["aluno_id"], str(l["aluno_id"]))
            saida.append({"metrica": m, "ranking": linhas})
        return saida
