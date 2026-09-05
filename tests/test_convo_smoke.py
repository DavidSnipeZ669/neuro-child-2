from neuro_child.gui import Brain, Memory, Personality, Eyes, Hands, Mouth
m = Memory()
p = Personality(m.profile)
e = Eyes()
h = Hands()
mo = Mouth()
b = Brain(m, p, e, h, mo)

for u in [
    'Hey darling',
    'How are you?',
    'Not really',
    'yeah, are you ready to talk to me now?',
    "I'll take that as a no then :(",
]:
    print('dad:', u)
    print('Nova:', b.respond(u))
    print()
