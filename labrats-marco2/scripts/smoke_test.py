import json
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"


def chamar(metodo, caminho, corpo=None):
    req = urllib.request.Request(BASE + caminho, method=metodo,
                                 data=json.dumps(corpo).encode() if corpo is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


falhas = 0


def verifica(nome, cond, extra=""):
    global falhas
    print(("  ok    " if cond else "  FALHA ") + nome + (f"  {extra}" if extra and not cond else ""))
    falhas += 0 if cond else 1


print("Aguardando as três bases…")
for _ in range(90):
    try:
        h = chamar("GET", "/health")[1]
        if h.get("redis") == h.get("cassandra") == h.get("mongodb") == "ok":
            break
    except Exception:
        pass
    time.sleep(3)
else:
    sys.exit("API/bases não ficaram prontas")

print("1) Dados de demonstração")
s, r = chamar("POST", "/admin/seed")
verifica("seed executou", s == 200 and r["alunos"] == 30, r)

print("2) Check-in (Redis) + histórico (Cassandra)")
aluno, academia = 15, (15 - 1) % 3 + 1          
chamar("POST", f"/checkout/{aluno}")            
antes = chamar("GET", f"/alunos/{aluno}/streak")[1]
verifica("streak inicial veio do histórico reconstruído", antes["atual"] >= 14, antes)
s, c1 = chamar("POST", "/checkin", {"aluno_id": aluno, "academia_id": academia})
verifica("check-in ok", s == 200 and c1["status"] == "ok", c1)
if antes["ultimo_dia"] != time.strftime("%Y-%m-%d"):
    verifica("streak incrementou", c1["streak"] == antes["atual"] + 1, c1)
s, c2 = chamar("POST", "/checkin", {"aluno_id": aluno, "academia_id": academia})
verifica("toque duplo é idempotente", c2["status"] == "ja_ativo", c2)
time.sleep(1.5)                                   
hist = chamar("GET", f"/alunos/{aluno}/historico?limite=3")[1]
verifica("check-in apareceu no Cassandra", len(hist) >= 1 and hist[0]["academia_id"] == academia, hist)
oc = chamar("GET", f"/academias/{academia}/painel")[1]
verifica("ocupação >= 1", oc["ocupacao_agora"] >= 1, oc["ocupacao_agora"])
verifica("picos por hora com 24 posições", len(oc["picos_por_hora"]) == 24)
rk = chamar("GET", f"/academias/{academia}/ranking")[1]
verifica("ranking contém o aluno", any(x["aluno_id"] == aluno for x in rk["ranking"]), rk)

print("3) Checkout")
s, co = chamar("POST", f"/checkout/{aluno}")
verifica("checkout ok", s == 200 and co["status"] == "encerrado", co)
s, _ = chamar("POST", f"/checkout/{aluno}")
verifica("checkout sem sessão = 404", s == 404)

print("4) Grupos de disputa (MongoDB)")
s, g = chamar("POST", "/grupos", {"nome": "Teste Smoke", "criador_id": 1, "metricas": [
    {"chave": "agachamento_kg", "nome": "Agachamento", "unidade": "kg", "modo": "maximo"},
    {"chave": "cintura_cm", "nome": "Cintura", "unidade": "cm", "modo": "queda"}]})
verifica("grupo criado", s == 201, g)
gid = g.get("id")
verifica("entrada de membro", chamar("POST", f"/grupos/{gid}/membros", {"aluno_id": 2})[0] == 201)
verifica("membro duplicado = 409", chamar("POST", f"/grupos/{gid}/membros", {"aluno_id": 2})[0] == 409)
verifica("métrica inexistente = 422", chamar("POST", f"/grupos/{gid}/registros", {"aluno_id": 2, "valores": {"foo": 1}})[0] == 422)
verifica("não-membro = 403", chamar("POST", f"/grupos/{gid}/registros", {"aluno_id": 9, "valores": {"cintura_cm": 80}})[0] == 403)
for aluno_id, ag, ci in ((1, 100, 90), (2, 120, 85)):
    chamar("POST", f"/grupos/{gid}/registros", {"aluno_id": aluno_id, "data": "2026-10-01", "valores": {"agachamento_kg": ag - 10, "cintura_cm": ci + 4}})
    chamar("POST", f"/grupos/{gid}/registros", {"aluno_id": aluno_id, "data": "2026-11-01", "valores": {"agachamento_kg": ag, "cintura_cm": ci}})
placar = chamar("GET", f"/grupos/{gid}/placar")[1]["placar"]
agach = next(b for b in placar if b["metrica"]["chave"] == "agachamento_kg")["ranking"]
cint = next(b for b in placar if b["metrica"]["chave"] == "cintura_cm")["ranking"]
verifica("maximo: líder tem 120 kg", agach[0]["score"] == 120, agach)
verifica("queda: ambos perderam 4 cm", {l["score"] for l in cint} == {4}, cint)

print("5) Reconstrução do Redis a partir do Cassandra")
s, rec = chamar("POST", f"/admin/reconstruir/{academia}")
verifica("reconstruído", s == 200 and rec["alunos"] > 0, rec)

print("\nTODOS OS TESTES PASSARAM" if not falhas else f"\n{falhas} FALHA(S)")
sys.exit(1 if falhas else 0)
