# LabRats — Marco 2

Persistência poliglota para um app de check-in em academias:

| Base | Papel | Onde está no código |
|---|---|---|
| **Redis** (master + réplica) | sessão de check-in (Hash+TTL), streak (Hash), ranking semanal (Sorted Set), ocupação (Sorted Set), fila de falhas (List) | `api/app/redis_store.py`, `api/app/lua/*.lua` |
| **Cassandra** | histórico durável (fonte da verdade): por academia/dia, por aluno, contador por hora | `api/app/cassandra_store.py`, `api/app/schema.cql` |
| **MongoDB** | perfil, academias, grupos de disputa e medidas (esquema flexível) | `api/app/mongo_store.py` |

## Como rodar

Requisitos: Docker + Docker Compose, ~3 GB de RAM livres.

```bash
docker compose up --build        # o Cassandra leva cerca de 1 minuto para ficar saudável
```

Abra **http://localhost:8000** (front) ou **http://localhost:8000/docs** (Swagger).
Na aba *Demo / admin*, clique em **Popular dados**.

Teste de ponta a ponta (outro terminal, só Python 3 padrão):

```bash
python3 scripts/smoke_test.py
```

Teste das regras do Redis, sem Docker (precisa de `redis-server` e `redis-cli` instalados):

```bash
bash tests/test_lua.sh
```

## Roteiro rápido de demonstração

1. **Check-in** (aba 1): escolha o *Aluno 5 (Elisa)* → streak 14 → *Fazer check-in* → streak 15.
2. Clique de novo em *Fazer check-in*: "toque duplo ignorado" (idempotência).
3. **Painel da academia** (aba 2): ocupação sobe para 1, ranking semanal e gráfico de horários de pico (6–8h e 18–20h).
4. **Grupos** (aba 3): placar com 3 métricas diferentes; crie um grupo novo com outras métricas.
5. **Resiliência** (terminal): `docker compose stop cassandra` → faça check-in: continua respondendo (AP);
   `docker compose start cassandra` → `curl -X POST localhost:8000/admin/reprocessar-fila`.
6. **Redis é derivado**: `docker compose exec redis redis-cli flushall` → aba 2 vazia →
   aba *Demo / admin* → *Reconstruir* → streak e ranking voltam a partir do Cassandra.

## Endpoints principais

`POST /checkin` · `POST /checkout/{aluno}` · `GET /alunos/{id}/streak` · `GET /alunos/{id}/historico` ·
`GET /academias/{id}/ranking` · `GET /academias/{id}/painel` · `POST /grupos` · `POST /grupos/{id}/membros` ·
`POST /grupos/{id}/registros` · `GET /grupos/{id}/placar` · `GET /health`

## Problemas comuns

- *API reiniciando no começo*: normal, ela espera o Cassandra (tenta por ~3 min). Veja `docker compose logs -f api`.
- *Pouca memória*: o Cassandra está limitado a 512 MB de heap em `docker-compose.yml`.
- *Porta 8000 ocupada*: troque `"8000:8000"` no compose.
