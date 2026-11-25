from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import TZ_APP

TZ = ZoneInfo(TZ_APP)


def agora() -> datetime:
    return datetime.now(TZ)


def dia_local(dt: datetime) -> date:
    return dt.astimezone(TZ).date()


def semana_iso(d: date) -> str:
    ano, sem, _ = d.isocalendar()
    return f"{ano}-W{sem:02d}"


def dias_da_semana(d: date) -> list[date]:
    segunda = d - timedelta(days=d.weekday())
    return [segunda + timedelta(days=i) for i in range(7)]


def de_cassandra(valor) -> datetime:
    """O driver devolve timestamp como datetime ingênuo em UTC."""
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return valor.astimezone(TZ)


def para_date(valor) -> date:
    """cassandra.util.Date -> datetime.date"""
    return valor if isinstance(valor, date) else valor.date()


def calc_streak(dias: set[date], hoje: date) -> tuple[int, int]:
    """(streak atual, melhor streak) a partir do conjunto de dias treinados."""
    if not dias:
        return 0, 0
    d = hoje if hoje in dias else hoje - timedelta(days=1)
    atual = 0
    while d in dias:
        atual += 1
        d -= timedelta(days=1)
    melhor = corrente = 0
    anterior = None
    for dia in sorted(dias):
        corrente = corrente + 1 if anterior and dia - anterior == timedelta(days=1) else 1
        melhor = max(melhor, corrente)
        anterior = dia
    return atual, melhor
