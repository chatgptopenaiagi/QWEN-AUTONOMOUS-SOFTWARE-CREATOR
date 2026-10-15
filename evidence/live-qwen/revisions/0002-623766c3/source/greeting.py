def greet(name, uppercase=False):
    greeting = f"Hello, {name}!"
    if uppercase:
        greeting = greeting.upper()
    return greeting