import os

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_REPLICA_HOST = os.getenv("REDIS_REPLICA_HOST", REDIS_HOST)
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
CASSANDRA_HOST = os.getenv("CASSANDRA_HOST", "localhost")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "labrats")
TZ_APP = os.getenv("TZ_APP", "America/Sao_Paulo")

TTL_SESSAO = 2 * 60 * 60            
TTL_RANKING = 21 * 24 * 60 * 60     
