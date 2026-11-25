-- Check-in atômico no Redis (um único round-trip, sem corrida entre requisições).
-- KEYS[1]=sessão do aluno   KEYS[2]=streak do aluno   KEYS[3]=ranking semanal da academia
-- KEYS[4]=presentes na academia (sorted set, score = instante de expiração)
-- ARGV: 1 aluno_id | 2 academia_id | 3 entrada_iso | 4 checkin_id | 5 hoje | 6 ontem
--       7 ttl_sessao (s) | 8 agora_epoch (s) | 9 ttl_ranking (s)

-- 1) Idempotência: se já existe sessão ativa, não conta de novo (duplo toque no totem/app)
if redis.call('EXISTS', KEYS[1]) == 1 then
  local s = redis.call('HMGET', KEYS[1], 'checkin_id', 'entrada', 'academia_id')
  local atual = tonumber(redis.call('HGET', KEYS[2], 'atual') or '0')
  local melhor = tonumber(redis.call('HGET', KEYS[2], 'melhor') or '0')
  return {'ja_ativo', atual, melhor, s[1], s[2], s[3]}
end

-- 2) Sessão volátil (Hash + TTL): expira sozinha se o aluno esquecer de fazer checkout
redis.call('HSET', KEYS[1], 'academia_id', ARGV[2], 'entrada', ARGV[3],
           'checkin_id', ARGV[4], 'entrada_epoch', ARGV[8], 'status', 'ativo')
redis.call('EXPIRE', KEYS[1], ARGV[7])

-- 3) Streak: só muda no primeiro check-in do dia
local ultimo = redis.call('HGET', KEYS[2], 'ultimo_dia')
local atual = tonumber(redis.call('HGET', KEYS[2], 'atual') or '0')
local melhor = tonumber(redis.call('HGET', KEYS[2], 'melhor') or '0')
local novo_dia = 0
if ultimo ~= ARGV[5] then
  novo_dia = 1
  if ultimo == ARGV[6] then atual = atual + 1 else atual = 1 end   -- ontem => continua; senão reinicia
  if atual > melhor then melhor = atual end
  redis.call('HSET', KEYS[2], 'atual', atual, 'ultimo_dia', ARGV[5], 'melhor', melhor)
  -- 4) Ranking semanal de assiduidade = nº de DIAS distintos treinados na semana
  redis.call('ZINCRBY', KEYS[3], 1, ARGV[1])
  redis.call('EXPIRE', KEYS[3], ARGV[9])
end

-- 5) Quem está na academia agora (ocupação): score = quando a sessão expira
redis.call('ZADD', KEYS[4], tonumber(ARGV[8]) + tonumber(ARGV[7]), ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[4], '-inf', ARGV[8])

return {'ok', atual, melhor, novo_dia}
