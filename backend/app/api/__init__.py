from . import auth, availability, calendar, events, members, native, notifications, push, rules, schedule, setup, solve, songs

ROUTERS = [
    setup.router,
    auth.router,
    members.router,
    events.router,
    songs.router,
    rules.router,
    availability.router,
    solve.router,
    schedule.router,
    calendar.router,
    notifications.router,
    push.router,
]
PUBLIC_ROUTERS = [calendar.public_router, native.public_router]  # 不带 /api 前缀
