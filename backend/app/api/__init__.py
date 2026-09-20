from . import auth, events, invites, members, setup, songs

ROUTERS = [setup.router, auth.router, members.router, invites.router, events.router, songs.router]
