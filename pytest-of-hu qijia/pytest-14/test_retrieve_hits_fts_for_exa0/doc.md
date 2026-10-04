# Redis

## 持久化

RDB 是定时快照。BGSAVE fork 子进程执行，SAVE 阻塞主线程。

## 主从复制

replication 异步，主写从读。

# MySQL

## 事务

MVCC 多版本并发控制，InnoDB 默认可重复读。
