"""Cassandra — histórico durável de check-ins (Unidade 3, Wide-Column). Fonte da verdade."""
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import UUID

from cassandra import ConsistencyLevel
from cassandra.cluster import Cluster

from . import config
from .timeutil import TZ, de_cassandra, dia_local

SCHEMA = Path(__file__).parent / "schema.cql"
CL = ConsistencyLevel.ONE       # AP: aceita responder com 1 réplica (consistência eventual)


class CassandraStore:
    def __init__(self):
        self.cluster = None
        self.s = None

    def conectar(self, tentativas: int = 60, espera: float = 3.0):
        ultimo = None
        for _ in range(tentativas):          # o Cassandra demora a subir: tenta por até ~3 min
            try:
                self.cluster = Cluster([config.CASSANDRA_HOST])
                self.s = self.cluster.connect()
                break
            except Exception as e:           # noqa: BLE001
                ultimo = e
                time.sleep(espera)
        else:
            raise RuntimeError(f"Cassandra indisponível: {ultimo}")
        for stmt in SCHEMA.read_text().split(";"):
            linhas = [l for l in stmt.splitlines() if not l.strip().startswith("--")]
            cql = "\n".join(linhas).strip()
            if cql:
                self.s.execute(cql)
        self.s.set_keyspace("labrats")
        P = self.s.prepare
        self.ins_acad = P("INSERT INTO checkins_por_academia (academia_id, dia, data_checkin, checkin_id, aluno_id, duracao_minutos) VALUES (?,?,?,?,?,?)")
        self.ins_aluno = P("INSERT INTO checkins_por_aluno (aluno_id, data_checkin, checkin_id, academia_id, duracao_minutos) VALUES (?,?,?,?,?)")
        self.inc_hora = P("UPDATE checkins_por_hora SET total = total + 1 WHERE academia_id=? AND dia=? AND hora=?")
        self.upd_acad = P("UPDATE checkins_por_academia SET duracao_minutos=? WHERE academia_id=? AND dia=? AND data_checkin=? AND checkin_id=?")
        self.upd_aluno = P("UPDATE checkins_por_aluno SET duracao_minutos=? WHERE aluno_id=? AND data_checkin=? AND checkin_id=?")
        self.sel_acad = P("SELECT data_checkin, aluno_id, duracao_minutos FROM checkins_por_academia WHERE academia_id=? AND dia=?")
        self.sel_aluno = P("SELECT data_checkin, academia_id, duracao_minutos FROM checkins_por_aluno WHERE aluno_id=? LIMIT ?")
        self.sel_aluno_desde = P("SELECT data_checkin, academia_id FROM checkins_por_aluno WHERE aluno_id=? AND data_checkin >= ?")
        self.sel_hora = P("SELECT hora, total FROM checkins_por_hora WHERE academia_id=? AND dia=?")
        for p in (self.ins_acad, self.ins_aluno, self.inc_hora, self.upd_acad, self.upd_aluno,
                  self.sel_acad, self.sel_aluno, self.sel_aluno_desde, self.sel_hora):
            p.consistency_level = CL

    def ping(self) -> bool:
        return self.s is not None and bool(self.s.execute("SELECT release_version FROM system.local").one())

    # ---- escrita ----
    def registrar_checkin(self, aluno_id: int, academia_id: int, quando: datetime, checkin_id: str,
                          duracao: int | None = None):
        """Upsert idempotente nas duas tabelas (retry seguro), depois o counter (não idempotente)."""
        dia = dia_local(quando)
        cid = UUID(checkin_id)
        f1 = self.s.execute_async(self.ins_acad, (academia_id, dia, quando, cid, aluno_id, duracao))
        f2 = self.s.execute_async(self.ins_aluno, (aluno_id, quando, cid, academia_id, duracao))
        f1.result(); f2.result()
        self.s.execute(self.inc_hora, (academia_id, dia, quando.astimezone(TZ).hour))

    def atualizar_duracao(self, aluno_id: int, academia_id: int, quando: datetime, checkin_id: str, minutos: int):
        cid = UUID(checkin_id)
        self.s.execute(self.upd_acad, (minutos, academia_id, dia_local(quando), quando, cid))
        self.s.execute(self.upd_aluno, (minutos, aluno_id, quando, cid))

    def checkins_academia(self, academia_id: int, de: date, ate: date, limite: int = 50) -> list[dict]:
        """Uma consulta por partição (academia, dia), do dia mais recente para o mais antigo."""
        saida, d = [], ate
        while d >= de and len(saida) < limite:
            for r in self.s.execute(self.sel_acad, (academia_id, d)):
                saida.append({"data_checkin": de_cassandra(r.data_checkin).isoformat(),
                              "aluno_id": r.aluno_id, "duracao_minutos": r.duracao_minutos})
                if len(saida) >= limite:
                    break
            d -= timedelta(days=1)
        return saida

    def picos_por_hora(self, academia_id: int, de: date, ate: date) -> list[int]:
        horas = [0] * 24
        d = de
        while d <= ate:
            for r in self.s.execute(self.sel_hora, (academia_id, d)):
                horas[r.hora] += r.total
            d += timedelta(days=1)
        return horas

    def alunos_no_dia(self, academia_id: int, dia: date) -> set[int]:
        return {r.aluno_id for r in self.s.execute(self.sel_acad, (academia_id, dia))}

    def historico_aluno(self, aluno_id: int, limite: int = 20) -> list[dict]:
        return [{"data_checkin": de_cassandra(r.data_checkin).isoformat(), "academia_id": r.academia_id,
                 "duracao_minutos": r.duracao_minutos}
                for r in self.s.execute(self.sel_aluno, (aluno_id, limite))]

    def dias_do_aluno(self, aluno_id: int, desde: datetime) -> list[tuple[date, int]]:
        """[(dia_local, academia_id)] — usado para reconstruir streak e ranking."""
        return [(dia_local(de_cassandra(r.data_checkin)), r.academia_id)
                for r in self.s.execute(self.sel_aluno_desde, (aluno_id, desde))]
