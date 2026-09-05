"""
Train English LLM on extracted corpus from B:\Local AI.
"""
import sys, random, time
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from neuro_child.english_llm import EnglishLLM, EnglishLLMConfig

CORPUS = Path(__file__).resolve().parent / 'memory' / 'english_corpus.txt'
texts = [line.strip() for line in CORPUS.read_text(encoding='utf-8').splitlines() if line.strip()]
random.shuffle(texts)
print('Loaded', len(texts), 'sentences')

config = EnglishLLMConfig(d_model=128, n_heads=4, n_layers=2, d_ff=256, max_seq_len=64, learning_rate=0.005)
model = EnglishLLM(config, force_new=True)
print('created', model.get_stats())

start = time.time()
for epoch in range(50):
    random.shuffle(texts)
    total = 0.0
    n = 0
    for text in texts:
        loss = model.train_step(text)
        total += loss
        n += 1
    avg = total / max(n, 1)
    if (epoch + 1) % 10 == 0:
        print(f'Epoch {epoch + 1}/50, avg loss {avg:.4f}, steps {model._training_steps}')
        model.save()
model.save()
print('done', round(time.time() - start, 1), 's')
print('stats', model.get_stats())
print('--- generation ---')
for p in ['Hello dad', 'I see', 'What are', 'I want to', 'The cat', 'Dad']:
    out = model.generate(p, max_new_tokens=30, temperature=0.75)
    print(p, '->', out)
