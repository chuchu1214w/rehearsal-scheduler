from . import auth, availability, events, members, rules, setup, songs

ROUTERS = [setup.router, auth.router, members.router, events.router, songs.router, rules.router, availability.router]
