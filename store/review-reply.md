# App Review 回复:Guideline 2.1 Information Needed(2026-09-28;2026-10-13 新构建更新)

同一段文字用两次:①「回复 App 审核」(附录屏视频);② 「App 审核信息 → 备注」(替换原来的备注)。
纯文本、不含密码(密码只放在「登录信息」栏,备注会沿用到以后的版本,写进去会过期)。长度需 ≤ 4000 字符。

---BEGIN---
Season - information for App Review

1. SCREEN RECORDING
Attached earlier (physical iPhone, TestFlight build): launch, sign-in, home, timetable, availability, notifications, push, Calendar, privacy policy and account deletion. No registration screen (the administrator creates accounts), no paid content or In-App Purchases.

2. PURPOSE AND AUDIENCE
Free rehearsal-scheduling app for one university dance club in South Korea (about 14 members). Members mark their free time on an hourly grid; the club administrator runs an automatic scheduler that keeps each song's members together and publishes the timetable. Members view it, get push notifications (published, room changed, reminder the day before) and can subscribe in the iOS Calendar. Audience: invited club members only. Developed by a club member as an individual developer.

3. HOW TO USE (interface in Simplified Chinese)
- Demo account: the member account in Sign-In Information (username appreview), in a sample event "审核演示 · 冬季公演" with fictional members and a published timetable.
- 排练表 tab: 我的时间表 / 全体成员 and 周日历 / 列表; ‹ › change weeks; tap a session for details; tap a date for that day.
- Availability: 排练表 tab > 修改空闲时间; choose 可排 / 尽量避开 / 不可排, tap or drag over slots, then 重新提交.
- Rehearsal room: a "Naver 地图" button next to a location opens it in the Naver Map app or website.
- Notifications: bell icon. Push: 开启推送通知 on the home card or in the 账号 tab. Calendar: 账号 > 添加到日历.
- Account deletion: 账号 > 注销账号 (link at the bottom) > enter password > 永久注销. Login account, sessions, notifications, push tokens and calendar subscription are deleted immediately; roster name and availability are deleted on request within 30 days (privacy policy). If the demo account is deleted, please reply for a new one.
- One club administrator account opens an administrator mode (adding members, running the scheduler, publishing, sharing a timetable image via the iOS share sheet). Not included because it shows real members' data; please ask if you need it.

4. EXTERNAL SERVICES
- Fly.io: our own backend server and database (Tokyo).
- Apple Push Notification service (APNs).
- Google OR-Tools: open-source solver library inside our server; no data goes to Google.
- Anthropic Claude API ("AI 调度员", administrator mode only, optional): when no valid timetable exists, the administrator may ask for suggestions. Before first use the app explains what is sent (the event's dates, songs, member nicknames, availability and special requirements; never usernames, passwords, push tokens or contact details) and starts only after the administrator taps 同意并开始. Nothing changes until the administrator approves each suggestion. Members cannot start it and the demo account does not see it. Disclosed in the privacy policy; members were notified of the update in the app.
- Naver Map: opened only when the user taps the button.
No third-party sign-in, payment, ads, analytics or tracking.

5. REGIONS
All territories except China mainland; identical features everywhere. Times are Korea Standard Time.

6. REGULATED INDUSTRY / THIRD-PARTY MATERIAL
Not applicable. Song titles are plain text; no music, video or other third-party media.

DISTRIBUTION (3.2)
The app is only useful to our club, so we have requested Unlisted App Distribution (Apple ID 6816253404); this version is set to manual release. Custom App distribution does not fit: the club is an informal student group, not a legal entity, so it cannot enroll in Apple Business Manager; members use personal iPhones and Apple Accounts.
---END---
