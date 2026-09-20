from . import auth, availability, events, members, rules, setup, solve, songs

ROUTERS = [setup.router, auth.router, members.router, events.router, songs.router, rules.router, availability.router, solve.router]
