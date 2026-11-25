-- Esquema Cassandra do LabRats (Marco 2). Modelagem query-first.
-- Em produção: NetworkTopologyStrategy com RF=3. No Docker (1 nó) usamos RF=1.
CREATE KEYSPACE IF NOT EXISTS labrats
  WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

-- Q1 (painel do dono): "check-ins da academia X no dia/intervalo Y"
-- Partition key composta (academia_id, dia): o bucket por dia evita a partição ilimitada
-- que existia no Marco 1 (academia_id sozinho cresceria para sempre).
CREATE TABLE IF NOT EXISTS labrats.checkins_por_academia (
  academia_id     int,
  dia             date,
  data_checkin    timestamp,
  checkin_id      uuid,
  aluno_id        int,
  duracao_minutos int,
  PRIMARY KEY ((academia_id, dia), data_checkin, checkin_id)
) WITH CLUSTERING ORDER BY (data_checkin DESC, checkin_id ASC);

-- Q2 (app do aluno): "meu histórico" — uma única partição por aluno
CREATE TABLE IF NOT EXISTS labrats.checkins_por_aluno (
  aluno_id        int,
  data_checkin    timestamp,
  checkin_id      uuid,
  academia_id     int,
  duracao_minutos int,
  PRIMARY KEY (aluno_id, data_checkin, checkin_id)
) WITH CLUSTERING ORDER BY (data_checkin DESC, checkin_id ASC);

-- Q3 (horários de pico): pré-agregação com COUNTER — leitura barata no painel
CREATE TABLE IF NOT EXISTS labrats.checkins_por_hora (
  academia_id int,
  dia         date,
  hora        int,
  total       counter,
  PRIMARY KEY ((academia_id, dia), hora)
);
