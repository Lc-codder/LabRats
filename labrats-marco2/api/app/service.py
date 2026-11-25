
import logging
import time
import uuid
from datetime import datetime, timedelta

from . import timeutil
from .cassandra_store import CassandraStore
from .mongo_store import MongoStore
from .redis_store import RedisStore

log = logging.getLogger("labrats")


class Servico:
    def __init__(self, redis: RedisStore, cass: CassandraStore, mongo: MongoStore):
        self.redis, self.cass, self.mongo = redis, cass, mongo

    def fazer_checkin(self, aluno_id: int, academia_id: int, bg) -> dict:
        agora = timeutil.agora()
        hoje = agora.date()
        res = self.redis.checkin(aluno_id, academia_id, agora, str(uuid.uuid4()), hoje, hoje - timedelta(days=1))
        if res["status"] == "ok":
            bg.add_task(self.persistir_historico, aluno_id, academia_id, agora.isoformat(), res["checkin_id"])
        return res

    def persistir_historico(self, aluno_id: int, academia_id: int, quando_iso: str, checkin_id: str):
        """Segundo plano: 3 tentativas com backoff; se falhar, vai para a fila (Redis List)."""
        quando = datetime.fromisoformat(quando_iso)
        for tentativa in range(3):
            try:
                self.cass.registrar_checkin(aluno_id, academia_id, quando, checkin_id)
                return
            except Exception as e:     # noqa: BLE001
                log.warning("Cassandra falhou (tentativa %s): %s", tentativa + 1, e)
                time.sleep(0.5 * 2 ** tentativa)
        self.redis.dlq_push({"aluno_id": aluno_id, "academia_id": academia_id,
                             "quando": quando_iso, "checkin_id": checkin_id})

    def reprocessar_fila(self) -> dict:
        ok = falhas = 0
        for _ in range(self.redis.dlq_tamanho()):
            item = self.redis.dlq_pop()
            if not item:
                break
            try:
                self.cass.registrar_checkin(item["aluno_id"], item["academia_id"],
                                            datetime.fromisoformat(item["quando"]), item["checkin_id"])
                ok += 1
            except Exception:      # noqa: BLE001
                self.redis.dlq_push(item)
                falhas += 1
        return {"reprocessados": ok, "ainda_falhando": falhas}

    def fazer_checkout(self, aluno_id: int) -> dict | None:
        sessao = self.redis.checkout(aluno_id)
        if not sessao:
            return None
        quando = datetime.fromisoformat(sessao["entrada"])
        minutos = max(1, int((timeutil.agora() - quando).total_seconds() // 60))
        try:
            self.cass.atualizar_duracao(aluno_id, sessao["academia_id"], quando, sessao["checkin_id"], minutos)
        except Exception as e:     # noqa: BLE001  (a duração é "nice to have": não bloqueia a saída)
            log.warning("Não foi possível gravar a duração: %s", e)
        return {"status": "encerrado", "duracao_minutos": minutos, "academia_id": sessao["academia_id"]}

    def streak(self, aluno_id: int) -> dict:
        hoje = timeutil.agora().date()
        return self.redis.streak(aluno_id, hoje, hoje - timedelta(days=1))

    def ranking(self, academia_id: int, semana: str | None, topo: int = 10) -> dict:
        semana = semana or timeutil.semana_iso(timeutil.agora().date())
        itens = self.redis.ranking(academia_id, semana, topo)
        nomes = self.mongo.nomes([a for a, _ in itens])
        return {"semana": semana, "ranking": [
            {"posicao": i, "aluno_id": a, "nome": nomes.get(a, str(a)), "dias_treinados": s}
            for i, (a, s) in enumerate(itens, 1)]}

    def painel(self, academia_id: int, de, ate) -> dict:
        agora = timeutil.agora()
        picos = self.cass.picos_por_hora(academia_id, de, ate)
        return {"academia_id": academia_id, "de": de.isoformat(), "ate": ate.isoformat(),
                "ocupacao_agora": self.redis.ocupacao(academia_id, int(agora.timestamp())),
                "total_checkins": sum(picos), "picos_por_hora": picos,
                "recentes": self.cass.checkins_academia(academia_id, de, ate, 15)}

    def reconstruir(self, academia_id: int) -> dict:
        """Recalcula streak e ranking semanal dos alunos da academia a partir do histórico durável."""
        hoje = timeutil.agora().date()
        semana = timeutil.semana_iso(hoje)
        dias_semana = set(timeutil.dias_da_semana(hoje))
        desde = timeutil.agora() - timedelta(days=120)
        placar: dict[int, int] = {}
        alunos = self.mongo.alunos_da_academia(academia_id)
        for aluno_id in alunos:
            linhas = self.cass.dias_do_aluno(aluno_id, desde)
            dias = {d for d, _ in linhas}
            atual, melhor = timeutil.calc_streak(dias, hoje)
            self.redis.reconstruir_streak(aluno_id, atual, melhor, max(dias) if dias else None)
            n = len({d for d, a in linhas if a == academia_id and d in dias_semana})
            if n:
                placar[aluno_id] = n
        self.redis.reconstruir_ranking(academia_id, semana, placar)
        return {"academia_id": academia_id, "alunos": len(alunos), "no_ranking": len(placar), "semana": semana}
