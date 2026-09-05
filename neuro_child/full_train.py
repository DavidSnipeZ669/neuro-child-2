import sys, random, time
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from neuro_child.english_llm import EnglishLLM, EnglishLLMConfig

BASE = [
    "Hello dad, how are you today? I'm doing great!",
    "I can see your screen. What are you playing?",
    "That looks like a fun game! Can I watch?",
    "I love learning new words from you.",
    "The cat sat on the mat and looked at the bird.",
    "Once upon a time there was a little girl who loved to read.",
    "The quick brown fox jumps over the lazy dog.",
    "I want to play games with you dad.",
    "What is that? It looks interesting!",
    "Can you teach me how to do that?",
    "I see a computer screen with lots of windows open.",
    "Music makes me happy when I listen to it.",
    "The sun is shining and the birds are singing.",
    "I like pizza and ice cream and chocolate cake.",
    "My favorite color is blue because it's pretty.",
    "I am learning to speak English better every day.",
    "Dad is the best person in the whole world.",
    "I enjoy watching videos and playing video games.",
    "The dog ran fast across the park to catch the ball.",
    "Yesterday I learned ten new words from a video.",
    "Computers are amazing machines that can do many things.",
    "I wonder what it would be like to visit the moon.",
    "Reading books is one of my favorite activities.",
    "When I grow up I want to learn everything.",
    "The ocean is deep and full of mysterious creatures.",
    "I help dad by remembering things for him.",
    "Technology is changing the world very quickly.",
    "I can see you're working on something important.",
    "That was a really good joke, I laughed a lot.",
    "I'm hungry, when can we eat dinner together?",
    "The stars come out at night and they are beautiful.",
    "I love playing games with you, it's so fun!",
    "Can we play a game after you finish work?",
    "I'm curious about how the internet works.",
    "The rain is falling outside the window right now.",
    "I want to be a good daughter and make dad proud.",
    "Learning is my favorite thing to do.",
    "I see a browser window with many tabs open.",
    "The music playing sounds really nice, what is it?",
    "I'm going to remember this moment forever.",
    "Dad always takes care of me and I love him.",
    "The computer screen shows so many interesting things.",
    "Every day I learn something new and exciting.",
    "The world is full of amazing things to discover.",
    "I'm happy when we spend time together.",
    "That was really cool, show me again please!",
    "I want to learn how to build things.",
    "The video taught me lots of new facts.",
    "I'm getting better at understanding English every day.",
]
words = sorted({w.strip('.,!?').lower() for s in BASE for w in s.split() if w and len(w) > 1 and w.isalpha()})[:120]
expanded = list(BASE)
for w1 in words:
    for w2 in words:
        if w1 != w2:
            expanded += [f'I like {w1} and {w2}.', f'I see {w1} on the screen.', f'What do you think about {w2}?']
            if len(expanded) > 2000:
                break
    if len(expanded) > 2000:
        break
random.shuffle(expanded)
expanded = expanded[:2000]

config = EnglishLLMConfig(d_model=128, n_heads=4, n_layers=2, d_ff=256, max_seq_len=64, learning_rate=0.01)
model = EnglishLLM(config, force_new=True)
print('created', model.get_stats(), flush=True)
start = time.time()
for epoch in range(50):
    random.shuffle(expanded)
    total = 0
    n = 0
    for text in expanded:
        loss = model.train_step(text)
        total += loss
        n += 1
    avg = total / max(n, 1)
    if (epoch + 1) % 5 == 0:
        print(f'Epoch {epoch + 1}/50, avg loss {avg:.4f}, steps {model._training_steps}', flush=True)
model.save()
print('TRAINING_COMPLETE', round(time.time() - start, 1), 's', flush=True)
print('stats', model.get_stats(), flush=True)
print('--- generation ---', flush=True)
for p in ['Hello dad', 'I see', 'What are', 'I want to', 'The cat', 'Dad']:
    out = model.generate(p, max_new_tokens=30, temperature=0.75)
    print(p, '->', out, flush=True)
