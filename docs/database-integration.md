# 演示数据库接入

数据库功能默认关闭。所有提供的健康记录、预警、号源、地点和预约均为虚构演示数据，不连接真实医院。普通健康问答仍使用原有规则，数据库记录不用于诊断。只有固定的 `demo-001` 虚构用户可查询个人演示记录；网页没有登录或真实身份认证。

## 开启 SQLite

根目录的 `digitalhelper_demo.sqlite3` 是可提交的种子库。复制 `.env.example` 为 `.env`，设置：

```dotenv
DIGITALHELPER_DB_ENABLED=true
DIGITALHELPER_DB_BACKEND=sqlite
# 可留空，默认使用 output/digitalhelper_demo.sqlite3
DIGITALHELPER_SQLITE_PATH=
```

重启 `run.cmd`。首次请求会复制种子库到运行路径，后续的模拟预约及预警确认只修改运行副本。运行路径位于已忽略 Git 的 `output/`；要重新演示初始数据，可在服务停止后删除该运行副本。数据库开启时会根据虚构的每周排班模板补足未来 14 天的日期号源，过去记录保留原日期，不会冒充当天数据。根目录种子库可以通过 `python -B -m vrm_demo.db.seed_demo` 在**文件不存在**时重新生成；脚本拒绝覆盖已有数据库。

演示数据包括 4 个科室、3 类每日时段、14 天的初始日期号源、不同余号和停诊情况、12 条历史预约、20 条健康记录、8 条不同状态的预警及服务说明。可以询问“内科什么时候有时间”“内科在哪里”“我的预约”“我的血压记录”“查看健康预警”。快捷选项包含具体日期、时段和余号。

确认预约前会重新查询该时段容量，并在事务中写入预约。前方人数 = 该时段预置的模拟已预约人数 + 本轮确认前已写入的有效演示预约数；不会推断现场候诊时间。重复提交同一确认令牌只产生一条记录。号源满额或数据库故障时不会返回预约成功。确认预警、稍后提醒和“联系家人”选择会改变演示预警状态；最后一种仅记录选择，不发送消息。

关闭 `DIGITALHELPER_DB_ENABLED` 后，预约与预警恢复原有规则回复，不访问数据库。`GET /api/health` 返回 `db_enabled`、`db_backend`、`db_available`，不包含路径、账户或密码。`POST /api/chat` 沿用原有字段；流程 `context` 在数据库模式下会增加科室、时段和幂等令牌，前端仍按原方式传回。

## MySQL 接口

安装可选连接依赖：

```powershell
python -m pip install -r requirements-mysql.txt
```

在**自行准备的空数据库**中手动执行 `vrm_demo/db/schema.mysql.sql`，按相同表结构导入自己的演示数据，并至少提供 `user_base.user_id = demo-001` 的虚构用户。MySQL 不会自动建表、补号源或写入示例记录；实际可约时段来自 `schedule` 表。`status` 应为 `open` 或 `closed`，预约状态为 `confirmed` 或 `cancelled`，预警状态为 `pending`、`confirmed`、`family_requested` 或 `later`。`schedule.base_booked` 表示系统接入前已占用的模拟名额，需满足 `0 <= base_booked <= capacity`；新确认的预约另存在 `appointment` 表。日期采用中国时区的门诊日期，接口查询未来 14 天。

```dotenv
DIGITALHELPER_DB_ENABLED=true
DIGITALHELPER_DB_BACKEND=mysql
DIGITALHELPER_MYSQL_HOST=127.0.0.1
DIGITALHELPER_MYSQL_PORT=3306
DIGITALHELPER_MYSQL_DATABASE=your_demo_database
DIGITALHELPER_MYSQL_USER=your_user
DIGITALHELPER_MYSQL_PASSWORD=your_password
```

MySQL 使用参数化查询，并在确认预约和更新预警时显式开启事务。代码测试使用模拟连接验证接口和事务，不连接或审查真实 MySQL 服务。连接失败时不泄露连接信息；涉及数据库的操作提示不可用，已进行的预约流程状态保留以便重试。
