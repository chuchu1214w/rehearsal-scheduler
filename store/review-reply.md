# App Review 回复:Guideline 2.1 Information Needed(2026-09-28)

同一段文字用两次:①「回复 App 审核」(附录屏视频);② 「App 审核信息 → 备注」(替换原来的备注)。
纯文本、不含密码(密码只放在「登录信息」栏,备注会沿用到以后的版本,写进去会过期)。长度需 ≤ 4000 字符。

---BEGIN---
Season - information for App Review

1. SCREEN RECORDING
Attached: physical iPhone, latest public iOS, this build from TestFlight. It shows launch, sign-in, home, timetable, availability, notifications, push, Calendar, privacy policy and account deletion. No registration screen (the administrator creates accounts), no content visible to other users (availability is seen only by the member and the administrator), no paid content or In-App Purchases. To keep the demo account usable, the recording signs in with and deletes a second sample member account (演示·小林).

2. PURPOSE AND AUDIENCE
Free rehearsal-scheduling app for one university dance club in South Korea (about 14 members): many song rehearsals must fit into members' class schedules, and a song's members should rehearse together. Members mark their free time for each day of the rehearsal period on an hourly grid. The club administrator runs an automatic scheduler that keeps each song's members together wherever possible and publishes the timetable. Members view their timetable, get push notifications when it is published or a rehearsal room changes (and a reminder the day before each rehearsal), and can subscribe to it in the iOS Calendar. Audience: invited club members only. Developed by a club member as an individual developer.

3. HOW TO USE (interface in Simplified Chinese)
- Demo account: the member account in Sign-In Information (username appreview), in a sample event "审核演示 · 冬季公演" with fictional members and a published timetable.
- Home (我的首页): first screen; tap the Season logo to return.
- 排练表 tab: switch 我的时间表 (mine) / 全体成员 (all) and 周日历 (week) / 列表 (list); 上周 / 下周 change weeks; tap a date to see that day.
- Availability: at the bottom of the 排练表 tab tap 修改空闲时间; choose 可排 / 尽量避开 / 不可排 (available / avoid / unavailable), tap or drag over slots, then tap 重新提交.
- Notifications: bell icon at the top right. Push: tap 开启推送通知 on the home screen card or in the 账号 (Account) tab.
- Calendar: 账号 tab > 添加到日历.
- Account deletion: 账号 tab > 注销账号 (small link at the bottom, next to 隐私政策) > enter password > 永久注销. The login account, sessions, notifications, push tokens and calendar subscription are deleted immediately. Roster name and submitted availability are club schedule records, deleted on request within 30 days (see privacy policy). If the demo account is deleted, please reply for a new one.
- Account types: besides members there is one club administrator account; it opens an administrator mode (in this app and on the website) for adding members, creating accounts, running the scheduler and publishing. We have not included it because it can see real members' personal data; please let us know if you need to review it.

4. EXTERNAL SERVICES
- Fly.io: hosts our own backend server and database (Tokyo).
- Apple Push Notification service (APNs).
- Google OR-Tools: open-source solver library running inside our server; no data is sent to Google.
No third-party sign-in, payment, ads, analytics, tracking or AI services. The calendar feed is standard ICS from our server.

5. REGIONS
Available in all territories except China mainland; features and content are identical everywhere. App times are Korea Standard Time; the Calendar app converts them to the device's time zone.

6. REGULATED INDUSTRY / THIRD-PARTY MATERIAL
Not applicable. Song titles are plain text; the app contains no music, video or other third-party media.

DISTRIBUTION (3.2)
The app is only useful to our club, so we have requested Unlisted App Distribution (Apple ID 6816253404) and this version is set to manual release. Custom App distribution does not fit: the club is an informal student group, not a legal entity, so it cannot enroll in Apple Business Manager; members use personal iPhones and personal Apple Accounts.
---END---
