"""Dados de demonstração: 3 academias, 30 alunos, 21 dias de histórico e um grupo de disputa."""
import random
import uuid
from datetime import datetime, timedelta

from . import timeutil

ACADEMIAS = [(1, "Power Gym Asa Norte"), (2, "Fit Taguatinga"), (3, "Muscle Sudoeste")]
NOMES = ["Ana", "Bruno", "Carla", "Diego", "Elisa", "Felipe", "Giovana", "Henrique", "Isabela", "João",
         "Karina", "Lucas", "Marina", "Nicolas", "Olívia", "Pedro", "Quésia", "Rafael", "Sara", "Tiago",
         "Úrsula", "Vitor", "Wesley", "Yasmin", "Zeca", "Alice", "Beto", "Camila", "Davi", "Eduarda"]


def popular(servico, dias: int = 21) -> dict:
    rnd = random.Random(42)                    
    m = servico.mongo.db
    ja_populado = m.alunos.count_documents({}) >= len(NOMES)   
    for aid, nome in ACADEMIAS:
        m.academias.replace_one({"_id": aid}, {"_id": aid, "nome": nome, "capacidade": 120}, upsert=True)
    for i, nome in enumerate(NOMES, 1):
        m.alunos.replace_one({"_id": i}, {"_id": i, "nome": nome, "academia_id": (i - 1) % 3 + 1}, upsert=True)

    hoje = timeutil.agora().date()
    total = 0
    for aluno_id in range(1, len(NOMES) + 1):
        academia = (aluno_id - 1) % 3 + 1
        constante = aluno_id % 5 == 0            
        for atras in range(0 if ja_populado else dias, 0, -1):   
            dia = hoje - timedelta(days=atras)
            if atras <= 14 and constante:
                treina = True
            else:
                treina = rnd.random() < 0.55
            if not treina:
                continue
            hora = rnd.choice([6, 7, 18, 19]) if rnd.random() < 0.85 else rnd.randint(9, 17)
            quando = datetime(dia.year, dia.month, dia.day, hora, rnd.randint(0, 59), tzinfo=timeutil.TZ)
            servico.cass.registrar_checkin(aluno_id, academia, quando, str(uuid.uuid4()), rnd.randint(40, 90))
            total += 1
    for aid, _ in ACADEMIAS:
        servico.reconstruir(aid)

    if m.grupos.count_documents({"nome": "Desafio Verão 2027"}) == 0:
        gid = servico.mongo.criar_grupo({
            "nome": "Desafio Verão 2027", "descricao": "Quem evolui mais em 8 semanas",
            "criador_id": 5,
            "metricas": [
                {"chave": "supino_kg", "nome": "Carga no supino", "unidade": "kg", "modo": "maximo"},
                {"chave": "peso_kg", "nome": "Perda de peso", "unidade": "kg", "modo": "queda"},
                {"chave": "braco_cm", "nome": "Braço", "unidade": "cm", "modo": "ganho"}]})
        for aluno_id in (5, 10, 15, 20):
            servico.mongo.adicionar_membro(gid, aluno_id, NOMES[aluno_id - 1])
            peso = rnd.uniform(70, 95)
            supino = rnd.uniform(50, 80)
            for semana in range(4):
                servico.mongo.registrar_medidas(
                    gid, aluno_id, hoje - timedelta(days=7 * (3 - semana)),
                    {"peso_kg": round(peso - semana * rnd.uniform(0.2, 1.2), 1),
                     "supino_kg": round(supino + semana * rnd.uniform(1, 5), 1),
                     "braco_cm": round(34 + semana * rnd.uniform(0, 0.6), 1)})
    return {"academias": len(ACADEMIAS), "alunos": len(NOMES), "checkins_historicos": total}
