"""Redis — dados voláteis e de acesso imediato (Unidade 2).
Escritas vão para o master; leituras pesadas (ranking, ocupação, streak) vão para a réplica."""
import json
from datetime import date, datetime
from pathlib import Path

import redis

from . import config
from .timeutil import semana_iso

LUA = Path(__file__).parent / "lua"


class RedisStore:
    def __init__(self):
        self.w = redis.Redis(host=config.REDIS_HOST, port=config.REDIS_PORT, decode_responses=True)
        self.r = redis.Redis(host=config.REDIS_REPLICA_HOST, port=config.REDIS_PORT, decode_responses=True)
        self._checkin = self.w.register_script((LUA / "checkin.lua").read_text())
        self._checkout = self.w.register_script((LUA / "checkout.lua").read_text())

    
    @staticmethod
    def k_sessao(aluno_id): return f"checkin:aluno:{aluno_id}"
    @staticmethod
    def k_streak(aluno_id): return f"streak:aluno:{aluno_id}"
    @staticmethod
    def k_ranking(academia_id, semana): return f"ranking:academia:{academia_id}:{semana}"
    @staticmethod
    def k_presentes(academia_id): return f"presentes:academia:{academia_id}"

    def ping(self) -> bool:
        return bool(self.w.ping())

    
    def checkin(self, aluno_id: int, academia_id: int, agora: datetime, checkin_id: str,
                hoje: date, ontem: date) -> dict:
        res = self._checkin(
            keys=[self.k_sessao(aluno_id), self.k_streak(aluno_id),
                  self.k_ranking(academia_id, semana_iso(hoje)), self.k_presentes(academia_id)],
            args=[aluno_id, academia_id, agora.isoformat(), checkin_id, hoje.isoformat(),
                  ontem.isoformat(), config.TTL_SESSAO, int(agora.timestamp()), config.TTL_RANKING],
        )
        if res[0] == "ja_ativo":
            return {"status": "ja_ativo", "streak": int(res[1]), "melhor_streak": int(res[2]),
                    "checkin_id": res[3], "entrada": res[4], "academia_id": int(res[5]) if res[5] else academia_id}
        return {"status": "ok", "streak": int(res[1]), "melhor_streak": int(res[2]),
                "novo_dia": bool(res[3]), "checkin_id": checkin_id, "entrada": agora.isoformat(),
                "academia_id": academia_id}

    def checkout(self, aluno_id: int):
        """Devolve dict da sessão encerrada, ou None se não havia sessão ativa."""
        academia_id = self.w.hget(self.k_sessao(aluno_id), "academia_id")
        if academia_id is None:
            return None
        res = self._checkout(keys=[self.k_sessao(aluno_id), self.k_presentes(academia_id)], args=[aluno_id])
        if not res:
            return None
        return {"checkin_id": res[0], "entrada": res[1], "academia_id": int(res[2]),
                "entrada_epoch": int(res[3])}

    
    def streak(self, aluno_id: int, hoje: date, ontem: date) -> dict:
        h = self.r.hgetall(self.k_streak(aluno_id))
        atual = int(h.get("atual", 0))
        if h.get("ultimo_dia") not in (hoje.isoformat(), ontem.isoformat()):
            atual = 0     
        return {"atual": atual, "melhor": int(h.get("melhor", 0)), "ultimo_dia": h.get("ultimo_dia")}

    def ranking(self, academia_id: int, semana: str, topo: int = 10) -> list[tuple[int, int]]:
        itens = self.r.zrevrange(self.k_ranking(academia_id, semana), 0, topo - 1, withscores=True)
        return [(int(a), int(s)) for a, s in itens]

    def ocupacao(self, academia_id: int, agora_epoch: int) -> int:
        
        return self.r.zcount(self.k_presentes(academia_id), agora_epoch, "+inf")

    
    def reconstruir_streak(self, aluno_id: int, atual: int, melhor: int, ultimo_dia: date | None):
        if ultimo_dia is None:
            return
        self.w.hset(self.k_streak(aluno_id),
                    mapping={"atual": atual, "melhor": melhor, "ultimo_dia": ultimo_dia.isoformat()})

    def reconstruir_ranking(self, academia_id: int, semana: str, placar: dict[int, int]):
        chave = self.k_ranking(academia_id, semana)
        pipe = self.w.pipeline()
        pipe.delete(chave)
        if placar:
            pipe.zadd(chave, {str(a): s for a, s in placar.items()})
            pipe.expire(chave, config.TTL_RANKING)
        pipe.execute()

    
    def dlq_push(self, item: dict):
        self.w.rpush("dlq:checkins", json.dumps(item))

    def dlq_pop(self):
        v = self.w.lpop("dlq:checkins")
        return json.loads(v) if v else None

    def dlq_tamanho(self) -> int:
        return self.w.llen("dlq:checkins")
