# 常见问题

## `locate` 找不到唯一函数

确认传入的是当前运行时的 `wrapper.node`。QQ 可能从 `versions/<curVersion>/QQUpdate.app/.../wrapper.node` 启动，而不是应用包内的基线模块。

如果诊断字符串或 ARM64 指令模式已经变化，说明当前 QQ 版本尚不受支持。请提交不含账号信息的 QQ 版本号、macOS 版本和错误信息；不要上传二进制、数据库或 key。

## LLDB 无法附加或启动

- 只调试本地 ad-hoc 副本；官方 hardened-runtime QQ 通常拒绝调试。
- 确认本地副本通过 `codesign --verify --deep --strict`。
- 不要关闭 SIP，也不要给 Terminal 永久注入权限。
- 系统可能要求授权开发者工具控制；只对当前操作授权。

## 所有 key 候选都被拒绝

- 确认隔离 QQ 实际打开了目标账号的 `nt_msg.db`。
- 确认 `CFFIXED_USER_HOME` 指向完整快照根，而不是 QQ 目录本身。
- 切换账号后需要重新捕获。
- 重装、迁移或安全状态变化后 key 可能改变。

## SQLCipher 报 `file is not a database`

常见原因是 key 不匹配、没有剥离 1024 字节 QQNT 头或 PRAGMA 顺序错误。本工具固定使用：

```sql
PRAGMA cipher_page_size = 4096;
PRAGMA key = '...';
PRAGMA kdf_iter = 4000;
PRAGMA cipher_hmac_algorithm = HMAC_SHA1;
PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;
```

如果数据库本身含损坏页，`sqlcipher_export` 可能失败。此时可参考 [QQBackup/nt_msg_db_util](https://github.com/QQBackup/nt_msg_db_util) 的逐表恢复方式。

## HTML 没有图片

- `--nt-data` 必须指向账号的 `nt_data` 根目录。
- 本地缓存只保存 QQ 曾下载过的资源；缺失资源不会联网补齐。
- `verify` 中资源数为 0 不代表消息文本导出失败。

## `bootstrap-exporter` 补丁无法应用

命令固定使用 README 中已测试的 QQNT_Export 提交。如果上游提交不可用或补丁失配，请查看本仓库 Release/Issue；不要直接对未知新版强制应用补丁。
