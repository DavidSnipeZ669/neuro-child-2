from neuro_child.standalone import Child

c = Child("child")
print("memory profile:", c.memory.profile)
print("observe:", c.eyes.observe())
print("reply:", c.brain.respond("hi"))
print("remember:", c.brain.remember("dad likes cats"))
print("recall:", c.memory.recall("cats"))
