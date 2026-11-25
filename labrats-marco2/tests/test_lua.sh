#!/usr/bin/env bash
# Testa as regras de negócio do Redis (streak, ranking, idempotência, ocupação, checkout)
# num redis-server local, sem Docker.  Uso: bash tests/test_lua.sh
set -u
P=6390; CLI="redis-cli -p $P"; D="$(cd "$(dirname "$0")/../api/app/lua" && pwd)"
redis-server --port $P --save "" --daemonize yes >/dev/null; sleep 0.5
trap '$CLI shutdown nosave >/dev/null 2>&1' EXIT
fail=0
check(){ if [ "$2" == "$3" ]; then echo "  ok   $1"; else echo "  FALHA $1: esperado [$3] obtido [$2]"; fail=1; fi; }
ci(){ # aluno academia hoje ontem agora  -> "status atual melhor novo_dia"
  $CLI --eval $D/checkin.lua "checkin:aluno:$1" "streak:aluno:$1" "ranking:academia:$2:W1" "presentes:academia:$2" , \
     $1 $2 "iso" "cid-$RANDOM" $3 $4 7200 $5 1000000 | paste -sd' ' | awk '{print $1,$2,$3,$4}'; }
sair(){ $CLI --eval $D/checkout.lua "checkin:aluno:$1" "presentes:academia:$2" , $1 | paste -sd' '; }

echo "1) primeiro check-in: streak 1, conta no ranking"
check "novo aluno" "$(ci 1 10 2026-11-01 2026-10-31 1000)" "ok 1 1 1"
echo "2) toque duplo (sessão ativa) é idempotente"
check "duplicado" "$(ci 1 10 2026-11-01 2026-10-31 1010 | cut -d' ' -f1)" "ja_ativo"
check "ranking = 1 dia" "$($CLI zscore ranking:academia:10:W1 1)" "1"
echo "3) checkout libera a sessão; novo check-in no MESMO dia não soma"
sair 1 10 >/dev/null
check "sessão removida" "$($CLI exists checkin:aluno:1)" "0"
check "mesmo dia: streak igual, sem novo dia" "$(ci 1 10 2026-11-01 2026-10-31 1100)" "ok 1 1 0"
check "ranking continua 1" "$($CLI zscore ranking:academia:10:W1 1)" "1"
echo "4) dia seguinte: streak continua"
sair 1 10 >/dev/null
check "dia 2" "$(ci 1 10 2026-11-02 2026-11-01 2000)" "ok 2 2 1"
sair 1 10 >/dev/null
check "dia 3" "$(ci 1 10 2026-11-03 2026-11-02 3000)" "ok 3 3 1"
echo "5) pulou um dia: streak reinicia, melhor é preservado"
sair 1 10 >/dev/null
check "pulou" "$(ci 1 10 2026-11-05 2026-11-04 5000)" "ok 1 3 1"
check "ranking = 4 dias" "$($CLI zscore ranking:academia:10:W1 1)" "4"
echo "6) ranking ordenado e ocupação"
ci 2 10 2026-11-05 2026-11-04 5001 >/dev/null
check "topo do ranking" "$($CLI zrevrange ranking:academia:10:W1 0 0 | head -1)" "1"
check "2 presentes agora" "$($CLI zcount presentes:academia:10 5002 +inf)" "2"
echo "7) checkout devolve a sessão e tira da ocupação"
sair 2 10 >/dev/null
check "1 presente" "$($CLI zcount presentes:academia:10 5002 +inf)" "1"
check "checkout sem sessão" "$(sair 2 10)" ""
echo "8) TTL da sessão"
check "TTL = 7200" "$($CLI ttl checkin:aluno:1)" "7200"
[ $fail -eq 0 ] && echo "TODOS OS TESTES PASSARAM" || { echo "HÁ FALHAS"; exit 1; }
