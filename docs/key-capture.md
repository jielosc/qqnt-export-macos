# 取 key 说明

## 为什么使用两次 `run`

QQ 的 `wrapper.node` 通常是运行时动态加载的。第一次启动只用于让 LLDB 认识该模块；中断后，`qqnt-install` 才能创建一个带模块归属的相对地址断点。杀掉并重新运行进程后，LLDB 会随 ASLR 重新解析断点。

如果直接在模块未加载时安装绝对地址断点，第二次启动的加载地址可能改变，断点可能失效。

## 为什么捕获多个候选

QQ 启动时会打开全局配置、账号资料、群资料、表情和消息等多个数据库。回调保存每个不同字节串的 SHA-256 指纹文件；`decrypt` 会用 SQLCipher 参数实际验证 `nt_msg.db`，不会根据长度或字符形态猜测。

## 寄存器约定

在已验证的 Apple Silicon QQNT 版本中，`nt_sqlite3_key_v2` 调用入口的相关参数为：

- `x2`：key 字节指针
- `x3`：key 长度

这是版本相关的实现细节。如果 QQ 更新后所有候选都不能解密：

1. 确认定位的是热更新目录中的实际 `wrapper.node`；
2. 用 LLDB 反汇编 `qqnt-install` 对应地址附近；
3. 确认函数开头仍保存 `x2/x3`；
4. 不要尝试把未知寄存器内容批量导出。

## 隔离路径

目标进程需要使用：

```text
CFFIXED_USER_HOME=/absolute/path/to/work/snapshot
```

快照内部必须存在：

```text
Library/Application Support/QQ
```

只设置 Electron/Chromium 的 `--user-data-dir` 并不能重定向 QQNT 内核数据库。

## 停止调试

捕获完成后务必：

```text
(lldb) process kill
(lldb) quit
```

随后正常启动 `/Applications/QQ.app`。临时 ad-hoc 副本不应作为日常 QQ 使用。
