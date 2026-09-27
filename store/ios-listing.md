# App Store 上架文案(Season)

按 App Store Connect 里的页面顺序排列,照着复制粘贴即可。

## 1. App 信息(左侧「App 信息」)
- 名称:Season
- 副标题(30 字内):舞团排练排程
- 主要语言:简体中文
- 类别:主要「效率」,次要「生活」
- 内容版权:不包含第三方内容
- 年龄分级:问卷全部选「无 / 否」→ 4+
  - 没有用户生成内容的公开分享、没有网页浏览器、没有赌博 / 暴力 / 医疗等内容
  - 「家长控制 / 年龄验证」等新问题同样选「否」

## 2. 定价与销售范围
- 价格:免费(0 档)
- 发布方式:审核通过后申请 **Unlisted(不公开列出)**,只把链接发给团员(见第 7 节)

## 3. App 隐私(左侧「App 隐私」)
- 隐私政策网址:https://timetomeet.fly.dev/privacy
- 「你或你的第三方合作伙伴是否从此 App 收集数据?」→ **是**
- 逐项勾选以下 4 类,每一类都答:用途 = **App 功能**;与用户身份关联 = **是**;用于追踪 = **否**

| 大类 | 具体类型 | 对应的数据 |
|---|---|---|
| 联系信息 | 姓名 | 管理员登记的名字 / 昵称 |
| 标识符 | 用户 ID | 用户名 |
| 用户内容 | 其他用户内容 | 填写的空闲时间表 |
| 使用数据 | 产品交互 | 最近登录、通知已读、空闲提交时间 |

- 不勾选:位置、联系人、健康、财务、浏览记录、搜索记录、诊断、设备 ID(APNs 推送令牌按苹果定义不算设备 ID,也不用于追踪)

## 4. 版本信息(「iOS App 1.0」页面)
### 截图
- 只需 **6.9 英寸 iPhone**(App 只支持 iPhone,其他尺寸苹果自动缩放),3–5 张:成员首页、填空闲涂格、周日历排练表、当天日程、通知
- 截图用审核演示数据,不出现真实团员名字

### 宣传文本(可选,170 字内)
舞团排练排程:成员填空闲,管理员一键排出排练表,变动即时推送。

### 描述
Season 是舞团内部使用的排练排程工具:

- 成员在手机上涂格子填写空闲时间,两分钟填完一周
- 管理员一键排程:自动满足"同一曲目的人必须同时在场"等硬性规则,并尽量减少来回奔波;成员直接看到排好的结果
- 排练表按课程表式周日历展示,点日期看当天日程,可切换"我的"和"全体"
- 排练表发布、排练地点更新、明天的排练,都会推送到手机
- 一键订阅到系统日历,变动自动更新

本 App 仅供受邀的舞团成员使用:账号由管理员开通,没有自助注册。

### 关键词(100 字内,逗号分隔)
排练,排程,舞团,日程,时间表,dance,rehearsal,schedule

### 技术支持网址
https://timetomeet.fly.dev/support

### 营销网址(可选)
留空

### 版权
2026 Season(或填你的名字 / 舞团名)

### 构建版本
选**最新**上传的构建(不要选 202609270036:那一版没有注销账号)

## 5. App 审核信息
- 需要登录:是。用户名 / 密码填**审核演示账号**(由 `scripts/make_review_demo.py` 创建:独立的演示演出 + 虚构成员,不接触真实团员数据)。不要用真人账号。
- 联系信息:你的姓名、电话、邮箱(只给苹果审核员看,不公开)
- 备注(英文,直接粘贴):

  Season is an internal scheduling app for a single dance club (about 14 members). Accounts are created by the club administrator; there is no self sign-up, no payments and no public content.

  The demo account is a regular member account in a sample event with fictional members and a published rehearsal timetable. Members submit their availability (tap/drag on the grid), view the rehearsal timetable, receive native push notifications (APNs) when the schedule or venue changes, and can subscribe to the timetable in the iOS Calendar. Scheduling itself is performed by the club administrator; members see the result.

  Account deletion: 账号 (Account) tab → bottom of the page → 注销账号 (Delete account). This is permanent, so please let us know if you delete the demo account and need a new one. The privacy policy link is in the same place.

  We intend to distribute this app as an Unlisted app (link-only) after approval.

## 6. 版本发布
- 选 **「手动发布此版本」**:审核通过后先别上架,等 Unlisted 申请批下来再发布,否则会先以公开可搜索的状态上架

## 7. 申请 Unlisted
- 提交审核的同时,填写苹果的 Unlisted App 申请表:https://developer.apple.com/contact/request/unlisted-app/
- 说明:内部使用的舞团排程工具,只面向受邀成员,附 App ID 6816253404
- 苹果批准后,App Store Connect 里点「发布此版本」,把 App Store 链接发到团员群
