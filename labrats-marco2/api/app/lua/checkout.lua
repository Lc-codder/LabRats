-- Checkout atômico: encerra a sessão e tira o aluno da lista de presentes.
-- KEYS[1]=sessão do aluno   KEYS[2]=presentes na academia   ARGV[1]=aluno_id
if redis.call('EXISTS', KEYS[1]) == 0 then
  return false
end
local s = redis.call('HMGET', KEYS[1], 'checkin_id', 'entrada', 'academia_id', 'entrada_epoch')
redis.call('DEL', KEYS[1])
redis.call('ZREM', KEYS[2], ARGV[1])
return s
