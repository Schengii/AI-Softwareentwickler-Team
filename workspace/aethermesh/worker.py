import asyncio

# FALSCH (blockiert den Event-Loop):
# result = ml_analyzer.predict(data)

# KORREKT (lagert in Thread-Pool aus):
result = await asyncio.to_thread(ml_analyzer.predict, data)
